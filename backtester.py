# backtester.py
"""
Parameter Optimizer & Backtesting Engine — v2 (Cycle-Aware)
Generates realistic synthetic BOOM/CRASH tick data, runs a full grid search
across all key strategy parameters INCLUDING the spike cycle counter params,
scores every combination, and writes the best-performing set to config.py.

Usage:
    python backtester.py                  # optimize BOOM1000 (default)
    python backtester.py CRASH1000        # optimize a different symbol
    python backtester.py BOOM1000 --apply # run + auto-apply without prompt
"""

import sys
import os
import json
import math
import random
import time
import itertools
from datetime import datetime
from evaluator import StrategyEvaluator
import config


# ─────────────────────────────────────────────
#  SILENT LOGGER  (no file I/O during optimization)
# ─────────────────────────────────────────────

class SilentLogger:
    """Drop-in replacement for TradeLogger that keeps trades in memory only."""
    def __init__(self):
        self._trades = []

    def log(self, *args, **kwargs):
        pass

    def log_trade(self, trade_id, symbol, direction, entry_price, exit_price,
                  pnl, balance, exit_reason, ticks_held, spike_detected):
        self._trades.append({
            "trade_id": trade_id, "symbol": symbol, "direction": direction,
            "entry_price": entry_price, "exit_price": exit_price,
            "pnl": round(pnl, 4), "balance": round(balance, 2),
            "exit_reason": exit_reason, "ticks_held": ticks_held,
            "spike_detected": spike_detected
        })

    def save_session_metrics(self, *args, **kwargs):
        pass

    def get_trades(self) -> list:
        return self._trades


# ─────────────────────────────────────────────
#  TICK GENERATOR
# ─────────────────────────────────────────────

def generate_ticks(n_ticks: int, symbol: str, seed: int = 42) -> list:
    """
    Produces a realistic synthetic price series for BOOM/CRASH indices.

    BOOM physics:  slow downward drift + occasional large upward spike
    CRASH physics: slow upward drift  + occasional large downward spike

    Spike probability matches the index number:
      BOOM1000 / CRASH1000 → 1 spike per ~1000 ticks
      BOOM500  / CRASH500  → 1 spike per ~500 ticks
    """
    rng = random.Random(seed)
    sym = symbol.upper()
    is_boom  = "BOOM"  in sym

    try:
        freq = int("".join(filter(str.isdigit, sym)))
    except ValueError:
        freq = 1000
    spike_prob = 1.0 / freq

    price = 14000.0
    drift = -0.035 if is_boom else +0.035
    noise = 0.12

    prices = []
    for _ in range(n_ticks):
        change = drift + rng.gauss(0, noise)
        if rng.random() < spike_prob:
            spike_size = rng.uniform(10.0, 28.0)
            change += spike_size if is_boom else -spike_size
        price = max(price + change, 1000.0)
        prices.append(round(price, 4))

    return prices


# ─────────────────────────────────────────────
#  INLINE FEATURE EXTRACTION
# ─────────────────────────────────────────────

def _calc_sma(prices, window):
    w = min(window, len(prices))
    return sum(prices[-w:]) / w if w else 0.0

def _calc_std(prices, window):
    w = min(window, len(prices))
    if w < 2:
        return 0.0
    sub  = prices[-w:]
    mean = sum(sub) / w
    return math.sqrt(sum((x - mean) ** 2 for x in sub) / (w - 1))

def _calc_rsi(prices, window=14):
    if len(prices) < window + 1:
        return 50.0
    gains, losses = [], []
    for i in range(len(prices) - window, len(prices)):
        d = prices[i] - prices[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag = sum(gains) / window
    al = sum(losses) / window
    if al == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + ag / al))

def _calc_ema(prices, window):
    if not prices:
        return 0.0
    alpha = 2.0 / (window + 1.0)
    ema   = prices[0]
    for p in prices[1:]:
        ema = alpha * p + (1.0 - alpha) * ema
    return ema

def _ema_slope(prices, window=10):
    if len(prices) < window + 3:
        return 0.0
    e1 = _calc_ema(prices[:-2], window)
    e3 = _calc_ema(prices,      window)
    return (e3 - e1) / 2.0

def _extract_features(prices, window):
    cp       = prices[-1]
    sma_slow = _calc_sma(prices, window)
    std_slow = _calc_std(prices, window)
    std_fast = _calc_std(prices, 5)
    rsi      = _calc_rsi(prices, 14)
    momentum = prices[-1] - prices[-6] if len(prices) >= 6 else 0.0
    z_score  = (cp - sma_slow) / std_slow if std_slow > 0 else 0.0
    comp     = std_fast / std_slow if std_slow > 0 else 1.0
    slope    = _ema_slope(prices, 10)
    micro    = _calc_std(prices, 2)
    return {
        "rsi": rsi, "z_score": z_score, "momentum": momentum,
        "compression_ratio": comp, "ema_slope": slope,
        "rolling_std_dev": std_slow, "micro_std": micro,
    }


# ─────────────────────────────────────────────
#  CYCLE STATE HELPER
# ─────────────────────────────────────────────

def _cycle_state(ticks_since_spike, cycle_len, early, hot, max_scale):
    """
    Returns (zone, rsi_bonus, lot_scale) for the current cycle position.

    zone      : RECOVERY | BUILDING | HOT | OVERDUE
    rsi_bonus : extra RSI headroom in HOT/OVERDUE (+5 = easier to enter)
    lot_scale : size multiplier for the next trade (1.0–max_scale)
    """
    pos = ticks_since_spike / cycle_len

    if pos < early:
        return "RECOVERY", 0, 1.0

    elif pos < hot:
        return "BUILDING", 0, 1.0

    elif pos < 1.0:
        progress  = (pos - hot) / (1.0 - hot)
        lot_scale = 1.0 + progress * (max_scale - 1.0)
        return "HOT", 5, round(min(lot_scale, max_scale), 3)

    else:
        return "OVERDUE", 5, round(min(max_scale, max_scale), 3)


# ─────────────────────────────────────────────
#  INLINE BACKTESTER  (fully cycle-aware)
# ─────────────────────────────────────────────

def run_backtest(symbol: str, ticks: list, params: dict) -> list:
    """
    Runs a full paper-trading simulation with all v2 logic:
      - Signal A requires RSI + squeeze/down-ticks confirmation
      - Post-trade cooldown prevents immediate re-entry
      - Spike cycle counter: RECOVERY blocks, HOT/OVERDUE relaxes + scales lots
      - OVERDUE zone triggers unconditional entry (Signal E)

    params keys (base):
        spike_threshold, rsi_oversold, rsi_overbought,
        squeeze_threshold, zscore_entry, exit_ticks,
        stop_loss_points, take_profit_points
    params keys (cycle — new):
        cooldown_ticks, cycle_early_zone, cycle_hot_zone, cycle_max_lot_scale
    """
    is_boom  = "BOOM"  in symbol.upper()
    is_crash = "CRASH" in symbol.upper()

    # ── Base params ──────────────────────────────────────────────────────────
    sp_factor = params["spike_threshold"]
    rsi_os    = params["rsi_oversold"]
    rsi_ob    = params["rsi_overbought"]
    sq_thresh = params["squeeze_threshold"]
    zs_thresh = params["zscore_entry"]
    max_ticks = params["exit_ticks"]
    sl_pts    = params["stop_loss_points"]
    tp_pts    = params["take_profit_points"]

    # ── Cycle params ─────────────────────────────────────────────────────────
    cooldown   = params.get("cooldown_ticks",        40)
    early_zone = params.get("cycle_early_zone",      0.25)
    hot_zone   = params.get("cycle_hot_zone",        0.70)
    max_scale  = params.get("cycle_max_lot_scale",   2.0)
    cycle_len  = 1000   # always 1000 for BOOM/CRASH 1000

    # ── State ─────────────────────────────────────────────────────────────────
    window = 50
    buf    = []

    direction   = None
    entry_price = None
    ticks_held  = 0
    lot         = 1.0

    ticks_since_last_close = cooldown         # start ready to trade
    ticks_since_spike      = cycle_len // 2   # start at 50% — neutral zone

    trades  = []
    balance = 1000.0

    for price in ticks:
        buf.append(price)
        if len(buf) > window * 2:
            buf.pop(0)
        if len(buf) < window:
            continue

        # ── Spike detection ───────────────────────────────────────────────────
        changes = [abs(buf[i] - buf[i-1]) for i in range(1, len(buf))]
        avg_chg  = sum(changes) / len(changes) if changes else 0.0001
        last_chg = buf[-1] - buf[-2]

        is_spike = False
        if is_boom  and last_chg >  avg_chg * sp_factor:
            is_spike = True
        if is_crash and last_chg < -avg_chg * sp_factor:
            is_spike = True

        # ── Cycle counter tick ────────────────────────────────────────────────
        ticks_since_spike += 1
        if is_spike:
            ticks_since_spike = 0   # reset immediately

        zone, rsi_bonus, lot_scale = _cycle_state(
            ticks_since_spike, cycle_len, early_zone, hot_zone, max_scale
        )

        # ── If in a trade: update it ──────────────────────────────────────────
        if direction is not None:
            ticks_held += 1
            pnl = (price - entry_price) * lot if direction == "BUY" \
                  else (entry_price - price) * lot

            should_exit = False
            exit_reason = ""
            spike_cap   = False

            if pnl <= -sl_pts * lot:
                should_exit = True
                exit_reason = "stop-loss"
            elif pnl >= tp_pts * lot:
                should_exit = True
                exit_reason = "take-profit"
            elif is_spike:
                good = (direction == "BUY" and last_chg > 0) or \
                       (direction == "SELL" and last_chg < 0)
                if good:
                    should_exit = True
                    exit_reason = "spike-captured"
                    spike_cap   = True
                elif pnl < 0:
                    should_exit = True
                    exit_reason = "adverse-spike"
            elif ticks_held >= max_ticks:
                should_exit = True
                exit_reason = "timeout"

            if should_exit:
                balance += pnl
                trades.append({
                    "pnl": round(pnl, 4), "balance": round(balance, 2),
                    "exit_reason": exit_reason, "ticks_held": ticks_held,
                    "spike_detected": spike_cap
                })
                direction   = None
                entry_price = None
                ticks_held  = 0
                ticks_since_last_close = 0   # start cooldown

            continue   # never open a new trade on the same tick as a close

        # ── Cooldown gate (flat position) ─────────────────────────────────────
        ticks_since_last_close += 1

        # ── RECOVERY zone: block all entries ─────────────────────────────────
        if zone == "RECOVERY":
            continue

        # ── Cooldown: skip if not enough ticks since last close ──────────────
        if ticks_since_last_close < cooldown:
            continue

        # ── Skip if this tick IS the spike (move is done) ────────────────────
        if is_spike:
            continue

        # ── Entry signals ─────────────────────────────────────────────────────
        feats      = _extract_features(buf, window)
        rsi        = feats["rsi"]
        comp       = feats["compression_ratio"]
        z          = feats["z_score"]
        slope      = feats["ema_slope"]
        mom        = feats["momentum"]
        micro      = feats["micro_std"]
        roll_std   = feats["rolling_std_dev"]
        is_sq      = comp < sq_thresh

        recent     = buf[-10:]
        down_ticks = sum(1 for i in range(1, len(recent)) if recent[i] < recent[i-1])
        up_ticks   = len(recent) - 1 - down_ticks
        micro_warn = micro > roll_std * 0.6

        eff_rsi_os = rsi_os + rsi_bonus   # HOT/OVERDUE: looser RSI threshold
        eff_rsi_ob = rsi_ob - rsi_bonus
        eff_zs     = zs_thresh * (0.7 if zone in ("HOT", "OVERDUE") else 1.0)

        entry_signal = False

        if is_boom:
            # Signal A: RSI oversold + squeeze or down-tick confirmation
            if rsi < eff_rsi_os and (is_sq or down_ticks >= 6):
                entry_signal = True
            # Signal B: Squeeze coil + z-score breakdown
            elif is_sq and z < -eff_zs and slope >= -0.005:
                entry_signal = True
            # Signal C: Momentum burst
            elif mom > 0 and slope > 0 and micro_warn:
                entry_signal = True
            # Signal D: Energy build-up
            elif down_ticks >= 8 and is_sq:
                entry_signal = True
            # Signal E: Cycle overdue — enter unconditionally
            elif zone == "OVERDUE":
                entry_signal = True

        elif is_crash:
            if rsi > eff_rsi_ob and (is_sq or up_ticks >= 6):
                entry_signal = True
            elif is_sq and z > eff_zs and slope <= 0.005:
                entry_signal = True
            elif mom < 0 and slope < 0 and micro_warn:
                entry_signal = True
            elif up_ticks >= 8 and is_sq:
                entry_signal = True
            elif zone == "OVERDUE":
                entry_signal = True

        if entry_signal:
            direction   = "BUY" if is_boom else "SELL"
            entry_price = price
            ticks_held  = 0
            lot         = lot_scale

    return trades


# ─────────────────────────────────────────────
#  GRID DEFINITIONS
# ─────────────────────────────────────────────

# Stage 1: Base strategy params (wide sweep, fast)
STAGE1_GRID = {
    "spike_threshold":    [2.5, 3.0, 4.0],
    "rsi_oversold":       [28, 35, 42],
    "rsi_overbought":     [58, 65, 72],
    "squeeze_threshold":  [0.75, 0.87],
    "zscore_entry":       [0.8, 1.1],
    "exit_ticks":         [60, 90, 120],
    "stop_loss_points":   [1.5, 2.5, 4.0],
    "take_profit_points": [8.0, 14.0, 20.0],
    # Fixed cycle defaults for Stage 1 (cycle params swept in Stage 2)
    "cooldown_ticks":        [40],
    "cycle_early_zone":      [0.25],
    "cycle_hot_zone":        [0.70],
    "cycle_max_lot_scale":   [2.0],
    # Total: 3×3×3×2×2×3×3×3 = 972 combos
}

# Stage 2: Cycle params swept over the top-N Stage 1 configs
CYCLE_GRID = {
    "cooldown_ticks":      [20, 40, 60],
    "cycle_early_zone":    [0.15, 0.25, 0.35],
    "cycle_hot_zone":      [0.60, 0.70, 0.80],
    "cycle_max_lot_scale": [1.5, 2.0, 2.5],
    # Total: 3×3×3×3 = 81 cycle combos
}


def _all_combos(grid: dict) -> list:
    keys   = list(grid.keys())
    values = list(grid.values())
    return [dict(zip(keys, combo)) for combo in itertools.product(*values)]


def _score_params(symbol, ticks_sets, params) -> float:
    """Average evaluator score across multiple tick seeds."""
    all_trades = []
    for ticks in ticks_sets:
        all_trades.extend(run_backtest(symbol, ticks, params))
    ev = StrategyEvaluator(all_trades)
    return ev.strategy_score()


# ─────────────────────────────────────────────
#  GRID SEARCH  (3-stage)
# ─────────────────────────────────────────────

def grid_search(symbol: str,
                n_ticks_s1: int = 1200,
                n_ticks_s2: int = 8000,
                seeds_s1: int   = 2,
                seeds_s2: int   = 5,
                top_n: int      = 5) -> dict:
    """
    Three-stage grid search:

    Stage 1 — Wide base sweep (972 combos, short ticks, fixed cycle defaults)
               → Finds top-N best base configurations.

    Stage 2 — Cycle param sweep (top-N × 81 cycle combos, long ticks)
               → For each top base config, tests all cycle parameter
                 combinations on much longer data.

    Stage 3 — Deep validation of the single overall winner on fresh seeds.
    """
    print(f"\n{'='*62}")
    print(f"  BRAIN OPTIMIZER v2 (Cycle-Aware) — {symbol}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*62}")

    # ── Stage 1: Wide base sweep ─────────────────────────────────────────────
    combos_s1 = _all_combos(STAGE1_GRID)
    total_s1  = len(combos_s1)
    ticks_s1  = [generate_ticks(n_ticks_s1, symbol, seed=s) for s in range(seeds_s1)]

    print(f"\n[STAGE 1] Base sweep   | {total_s1} combos × {seeds_s1} seeds × {n_ticks_s1} ticks")

    results_s1 = []
    t0 = time.time()
    for i, params in enumerate(combos_s1):
        score = _score_params(symbol, ticks_s1, params)
        results_s1.append((score, params))
        if (i + 1) % 200 == 0 or (i + 1) == total_s1:
            elapsed = time.time() - t0
            pct     = (i + 1) / total_s1 * 100
            eta     = elapsed / (i + 1) * (total_s1 - i - 1)
            print(f"  {i+1:>5}/{total_s1}  ({pct:.0f}%)  ETA {eta:.0f}s  "
                  f"best so far: {max(r[0] for r in results_s1):.2f}")

    results_s1.sort(key=lambda x: x[0], reverse=True)
    top_base = [p for _, p in results_s1[:top_n]]
    print(f"\n  Stage 1 done. Best: {results_s1[0][0]:.2f} | "
          f"Top-{top_n} advancing to cycle sweep…")

    # ── Stage 2: Cycle param sweep over top-N base configs ──────────────────
    cycle_combos = _all_combos(CYCLE_GRID)
    n_s2         = len(top_base) * len(cycle_combos)
    ticks_s2     = [generate_ticks(n_ticks_s2, symbol, seed=200 + s) for s in range(seeds_s2)]

    print(f"\n[STAGE 2] Cycle sweep  | {top_n} base × {len(cycle_combos)} cycle "
          f"= {n_s2} combos × {seeds_s2} seeds × {n_ticks_s2} ticks")

    results_s2 = []
    t0 = time.time()
    counter = 0
    for base in top_base:
        for cyc in cycle_combos:
            params = {**base, **cyc}   # merge base + cycle params
            score  = _score_params(symbol, ticks_s2, params)
            results_s2.append((score, params))
            counter += 1
            if counter % 50 == 0 or counter == n_s2:
                elapsed = time.time() - t0
                pct     = counter / n_s2 * 100
                eta     = elapsed / counter * (n_s2 - counter)
                print(f"  {counter:>5}/{n_s2}  ({pct:.0f}%)  ETA {eta:.0f}s  "
                      f"best so far: {max(r[0] for r in results_s2):.2f}")

    results_s2.sort(key=lambda x: x[0], reverse=True)
    best_score_s2, best_params = results_s2[0]
    print(f"\n  Stage 2 done. Best composite score: {best_score_s2:.2f}")

    # ── Stage 3: Deep validation of the overall winner ───────────────────────
    print(f"\n[STAGE 3] Final valid  | 1 winner × 8 seeds × {n_ticks_s2} ticks")
    ticks_s3 = [generate_ticks(n_ticks_s2, symbol, seed=500 + s) for s in range(8)]
    all_trades = []
    for ticks in ticks_s3:
        all_trades.extend(run_backtest(symbol, ticks, best_params))

    ev = StrategyEvaluator(all_trades)
    report      = ev.full_report()
    final_score = ev.strategy_score()
    print(f"  Final validated score: {final_score:.2f}")

    return {
        "symbol":       symbol,
        "score":        final_score,
        "params":       best_params,
        "report":       report,
        "stage1_best":  results_s1[0][0],
        "stage2_best":  best_score_s2,
        "all_stage2":   [(s, p) for s, p in results_s2[:10]]
    }


# ─────────────────────────────────────────────
#  CONFIG WRITER
# ─────────────────────────────────────────────

def apply_params_to_config(params: dict, symbol: str):
    """
    Writes optimized parameters back into config.py in-place.
    Handles both base params and new cycle params.
    """
    config_path = os.path.join(os.path.dirname(__file__), "config.py")
    with open(config_path, "r") as f:
        lines = f.readlines()

    replacements = {
        "SPIKE_THRESHOLD_FACTOR":  params["spike_threshold"],
        "RSI_OVERSOLD":            params["rsi_oversold"],
        "RSI_OVERBOUGHT":          params["rsi_overbought"],
        "SQUEEZE_THRESHOLD":       params["squeeze_threshold"],
        "ZSCORE_ENTRY":            params["zscore_entry"],
        "BOOM_EXIT_TICKS":         params["exit_ticks"],
        "CRASH_EXIT_TICKS":        params["exit_ticks"],
        "STOP_LOSS_POINTS":        params["stop_loss_points"],
        "TAKE_PROFIT_POINTS":      params["take_profit_points"],
        "POST_TRADE_COOLDOWN_TICKS": params.get("cooldown_ticks", 40),
        "CYCLE_EARLY_ZONE":        params.get("cycle_early_zone", 0.25),
        "CYCLE_HOT_ZONE":          params.get("cycle_hot_zone", 0.70),
        "CYCLE_MAX_LOT_SCALE":     params.get("cycle_max_lot_scale", 2.0),
    }

    new_lines = []
    for line in lines:
        written = False
        for key, val in replacements.items():
            if line.strip().startswith(key + " "):
                comment = ""
                if "#" in line:
                    comment = "  " + line[line.index("#"):]
                else:
                    comment = "\n"
                new_lines.append(
                    f"{key} = {val}"
                    f"{comment if comment.endswith(chr(10)) else comment + chr(10)}"
                )
                written = True
                break
        if not written:
            new_lines.append(line)

    with open(config_path, "w") as f:
        f.writelines(new_lines)

    print(f"\n[CONFIG] config.py updated with all optimized parameters.")


def save_optimization_report(result: dict):
    """Saves the full optimization report to logs/optimization_report.json."""
    os.makedirs("logs", exist_ok=True)
    path = "logs/optimization_report.json"
    report_data = {
        "timestamp":         datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "optimizer_version": "v2-cycle-aware",
        "symbol":            result["symbol"],
        "best_score":        result["score"],
        "stage1_best":       result["stage1_best"],
        "stage2_best":       result["stage2_best"],
        "best_params":       result["params"],
        "performance_report": result["report"],
        "top10_stage2": [
            {"rank": i+1, "score": round(s, 2), "params": p}
            for i, (s, p) in enumerate(result["all_stage2"])
        ]
    }
    with open(path, "w") as f:
        json.dump(report_data, f, indent=4)
    print(f"[REPORT] Saved → {path}")


# ─────────────────────────────────────────────
#  RESULTS PRINTER
# ─────────────────────────────────────────────

def print_results(result: dict):
    sym    = result["symbol"]
    score  = result["score"]
    params = result["params"]
    rep    = result["report"]

    print(f"\n{'='*62}")
    print(f"  OPTIMIZATION COMPLETE — {sym}")
    print(f"{'='*62}")
    print(f"\n  BEST COMPOSITE SCORE : {score:.2f} / 100")
    print(f"  (Stage 1: {result['stage1_best']:.2f}  Stage 2: {result['stage2_best']:.2f})")

    print(f"\n  PERFORMANCE METRICS:")
    print(f"    Trades         : {rep['total_trades']}")
    print(f"    Win Rate       : {rep['win_rate']*100:.1f}%")
    print(f"    Net Profit     : ${rep['net_profit']:+.2f}")
    print(f"    Profit Factor  : {rep['profit_factor']:.2f}x")
    print(f"    Max Drawdown   : ${rep['max_drawdown']:.2f}")
    print(f"    Spike Catches  : {rep['spike_capture_ratio']*100:.1f}%")
    print(f"    Timeout Ratio  : {rep['timeout_ratio']*100:.1f}%")
    print(f"    Max Loss Streak: {rep['loss_streak']} trades")

    print(f"\n  OPTIMAL BASE PARAMETERS:")
    print(f"    Spike Threshold  : {params['spike_threshold']}")
    print(f"    RSI Oversold     : {params['rsi_oversold']}")
    print(f"    RSI Overbought   : {params['rsi_overbought']}")
    print(f"    Squeeze Threshold: {params['squeeze_threshold']}")
    print(f"    Z-Score Entry    : {params['zscore_entry']}")
    print(f"    Exit Ticks       : {params['exit_ticks']}")
    print(f"    Stop Loss (pts)  : {params['stop_loss_points']}")
    print(f"    Take Profit (pts): {params['take_profit_points']}")

    print(f"\n  OPTIMAL CYCLE PARAMETERS:")
    print(f"    Cooldown Ticks   : {params.get('cooldown_ticks', 40)}")
    print(f"    Cycle Early Zone : {params.get('cycle_early_zone', 0.25)}  "
          f"({int(params.get('cycle_early_zone',0.25)*1000)} ticks)")
    print(f"    Cycle Hot Zone   : {params.get('cycle_hot_zone', 0.70)}  "
          f"({int(params.get('cycle_hot_zone',0.70)*1000)} ticks)")
    print(f"    Max Lot Scale    : {params.get('cycle_max_lot_scale', 2.0)}x")

    print(f"\n  TOP 5 ALTERNATIVES:")
    for i, (s, p) in enumerate(result["all_stage2"][:5]):
        print(f"    #{i+1}  Score {s:.2f} | "
              f"SL={p['stop_loss_points']} TP={p['take_profit_points']} "
              f"Exit={p['exit_ticks']} RSI<{p['rsi_oversold']} "
              f"CD={p.get('cooldown_ticks',40)} "
              f"Hot@{int(p.get('cycle_hot_zone',0.70)*100)}%")
    print()


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    args       = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags      = [a for a in sys.argv[1:] if a.startswith("--")]
    auto_apply = "--apply" in flags

    symbol = args[0].upper() if args else config.ACTIVE_SYMBOL

    result = grid_search(symbol)
    print_results(result)
    save_optimization_report(result)

    if auto_apply:
        apply_params_to_config(result["params"], symbol)
        print("\n[AUTO] Parameters applied to config.py (--apply flag was set).")
    else:
        print("─" * 62)
        ans = input("  Apply these parameters to config.py? [y/N]: ").strip().lower()
        if ans == "y":
            apply_params_to_config(result["params"], symbol)
            print("\n[DONE] Brain update applied. Restart the bot to use new params.")
        else:
            print("\n[SKIP] config.py unchanged. Report saved to logs/.")
