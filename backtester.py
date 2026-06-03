# backtester.py
"""
Parameter Optimizer & Backtesting Engine
Generates realistic synthetic BOOM/CRASH tick data, runs a full grid search
across all key strategy parameters, scores every combination, and writes the
best-performing parameter set directly to config.py as a "brain update".

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
            "trade_id": trade_id,
            "symbol": symbol,
            "direction": direction,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl": round(pnl, 4),
            "balance": round(balance, 2),
            "exit_reason": exit_reason,
            "ticks_held": ticks_held,
            "spike_detected": spike_detected
        })

    def save_session_metrics(self, *args, **kwargs):
        pass

    def get_trades(self) -> list:
        return self._trades


# ─────────────────────────────────────────────
#  TICK GENERATOR
# ─────────────────────────────────────────────

def generate_ticks(n_ticks: int, symbol: str, seed: int = 42) -> list[float]:
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
    is_crash = "CRASH" in sym

    # Spike frequency from symbol name
    try:
        freq = int("".join(filter(str.isdigit, sym)))
    except ValueError:
        freq = 1000
    spike_prob = 1.0 / freq

    # Base market parameters
    price  = 14000.0
    drift  = -0.035 if is_boom else +0.035   # between-spike trend direction
    noise  = 0.12                             # tick-to-tick randomness (std-dev)

    prices = []
    for _ in range(n_ticks):
        change = drift + rng.gauss(0, noise)

        if rng.random() < spike_prob:
            spike_size = rng.uniform(10.0, 28.0)
            change += spike_size if is_boom else -spike_size

        price += change
        # Keep price from going negative or exploding
        price = max(price, 1000.0)
        prices.append(round(price, 4))

    return prices


# ─────────────────────────────────────────────
#  INLINE BACKTESTER (fast, no config mutation)
# ─────────────────────────────────────────────

def _calc_sma(prices, window):
    w = min(window, len(prices))
    return sum(prices[-w:]) / w if w else 0.0

def _calc_std(prices, window):
    w = min(window, len(prices))
    if w < 2:
        return 0.0
    sub = prices[-w:]
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
    ema = prices[0]
    for p in prices[1:]:
        ema = alpha * p + (1.0 - alpha) * ema
    return ema

def _ema_slope(prices, window=10):
    if len(prices) < window + 3:
        return 0.0
    e1 = _calc_ema(prices[:-2], window)
    e2 = _calc_ema(prices[:-1], window)
    e3 = _calc_ema(prices,      window)
    return (e3 - e1) / 2.0

def _extract_features(prices, window):
    cp = prices[-1]
    sma_slow = _calc_sma(prices, window)
    std_slow  = _calc_std(prices, window)
    std_fast  = _calc_std(prices, 5)
    rsi       = _calc_rsi(prices, 14)
    momentum  = prices[-1] - prices[-6] if len(prices) >= 6 else 0.0
    z_score   = (cp - sma_slow) / std_slow if std_slow > 0 else 0.0
    comp      = std_fast / std_slow if std_slow > 0 else 1.0
    slope     = _ema_slope(prices, 10)
    micro_std = _calc_std(prices, 2)
    return {
        "rsi": rsi, "z_score": z_score, "momentum": momentum,
        "compression_ratio": comp, "ema_slope": slope,
        "rolling_std_dev": std_slow, "micro_std": micro_std,
    }


def run_backtest(symbol: str, ticks: list[float], params: dict) -> list[dict]:
    """
    Runs a full paper-trading simulation on the given tick series using the
    supplied parameter dict. Returns a list of closed trade records.

    params keys:
        spike_threshold   — multiplier of mean tick change to flag a spike
        rsi_oversold      — RSI level below which BOOM enters BUY
        rsi_overbought    — RSI level above which CRASH enters SELL
        squeeze_threshold — compression ratio threshold for squeeze detection
        zscore_entry      — absolute z-score threshold for squeeze entry
        exit_ticks        — max ticks to hold before timeout exit
        stop_loss_points  — price points against entry before stop-loss
        take_profit_points— price points in favour before locking profit
    """
    is_boom  = "BOOM"  in symbol.upper()
    is_crash = "CRASH" in symbol.upper()

    sp_factor  = params["spike_threshold"]
    rsi_os     = params["rsi_oversold"]
    rsi_ob     = params["rsi_overbought"]
    sq_thresh  = params["squeeze_threshold"]
    zs_thresh  = params["zscore_entry"]
    max_ticks  = params["exit_ticks"]
    sl_pts     = params["stop_loss_points"]
    tp_pts     = params["take_profit_points"]
    lot        = 1.0
    window     = 50

    trades   = []
    balance  = 1000.0
    buf      = []

    # Active trade state
    direction    = None
    entry_price  = None
    ticks_held   = 0

    for price in ticks:
        buf.append(price)
        if len(buf) > window * 2:
            buf.pop(0)
        if len(buf) < window:
            continue

        # ── Spike detection ──
        changes = [abs(buf[i] - buf[i-1]) for i in range(1, len(buf))]
        avg_chg  = sum(changes) / len(changes) if changes else 0.0001
        last_chg = buf[-1] - buf[-2]

        is_spike = False
        if is_boom  and last_chg >  avg_chg * sp_factor:
            is_spike = True
        if is_crash and last_chg < -avg_chg * sp_factor:
            is_spike = True

        # ── If in a trade, update it ──
        if direction is not None:
            ticks_held += 1
            pnl = (price - entry_price) * lot if direction == "BUY" else (entry_price - price) * lot

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
                good_spike = (direction == "BUY" and last_chg > 0) or (direction == "SELL" and last_chg < 0)
                if good_spike:
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
                    "pnl": round(pnl, 4),
                    "balance": round(balance, 2),
                    "exit_reason": exit_reason,
                    "ticks_held": ticks_held,
                    "spike_detected": spike_cap
                })
                direction   = None
                entry_price = None
                ticks_held  = 0
            continue   # don't consider new entry on same tick

        # ── Entry logic ──
        feats     = _extract_features(buf, window)
        rsi       = feats["rsi"]
        comp      = feats["compression_ratio"]
        z         = feats["z_score"]
        slope     = feats["ema_slope"]
        mom       = feats["momentum"]
        micro     = feats["micro_std"]
        roll_std  = feats["rolling_std_dev"]
        is_sq     = comp < sq_thresh

        recent     = buf[-10:]
        down_ticks = sum(1 for i in range(1, len(recent)) if recent[i] < recent[i-1])
        up_ticks   = len(recent) - 1 - down_ticks
        micro_warn = micro > roll_std * 0.6

        entry_signal = False
        if is_boom:
            if rsi < rsi_os:
                entry_signal = True
            elif is_sq and z < -zs_thresh and slope >= -0.005:
                entry_signal = True
            elif mom > 0 and slope > 0 and micro_warn:
                entry_signal = True
            elif down_ticks >= 8 and is_sq:
                entry_signal = True

        elif is_crash:
            if rsi > rsi_ob:
                entry_signal = True
            elif is_sq and z > zs_thresh and slope <= 0.005:
                entry_signal = True
            elif mom < 0 and slope < 0 and micro_warn:
                entry_signal = True
            elif up_ticks >= 8 and is_sq:
                entry_signal = True

        if entry_signal:
            direction   = "BUY" if is_boom else "SELL"
            entry_price = price
            ticks_held  = 0

    return trades


# ─────────────────────────────────────────────
#  GRID SEARCH
# ─────────────────────────────────────────────

STAGE1_GRID = {
    # High-impact: stop-loss, exit window, take-profit, rsi threshold
    "spike_threshold":    [2.5, 3.0, 4.0],
    "rsi_oversold":       [28, 35, 42],
    "rsi_overbought":     [58, 65, 72],
    "squeeze_threshold":  [0.75, 0.87],
    "zscore_entry":       [0.8, 1.1],
    "exit_ticks":         [60, 90, 120],
    "stop_loss_points":   [1.5, 2.5, 4.0],
    "take_profit_points": [8.0, 14.0, 20.0],
    # Total: 3×3×3×2×2×3×3×3 = 972 combos (fast)
}

STAGE2_REFINE = {
    # Narrowed around stage-1 winner (filled dynamically)
    "spike_threshold":    [],
    "rsi_oversold":       [],
    "rsi_overbought":     [],
    "squeeze_threshold":  [],
    "zscore_entry":       [],
    "exit_ticks":         [],
    "stop_loss_points":   [],
    "take_profit_points": [],
}


def _all_combos(grid: dict) -> list[dict]:
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


def _refine_grid(winner: dict, stage1_grid: dict) -> dict:
    """Build a tighter grid around the stage-1 winner."""
    refined = {}
    for key, val in winner.items():
        options = stage1_grid[key]
        idx = options.index(val)
        lower = options[idx - 1] if idx > 0 else val
        upper = options[idx + 1] if idx < len(options) - 1 else val
        # 3 mid-points between lower and upper
        if isinstance(val, int):
            mid = sorted(set([lower, round((lower + val) / 2), val,
                               round((val + upper) / 2), upper]))
        else:
            mid = sorted(set([lower, round((lower + val) / 2, 4), val,
                               round((val + upper) / 2, 4), upper]))
        refined[key] = mid
    return refined


def grid_search(symbol: str, n_ticks_s1: int = 1200, n_ticks_s2: int = 8000,
                seeds_s1: int = 2, seeds_s2: int = 5, top_n: int = 10) -> dict:
    """
    Two-stage grid search.
    Stage 1: Wide grid, short tick series — finds top-N candidates fast.
    Stage 2: Revalidates top-N with much longer series for accuracy.
    Returns the best params dict with its full evaluator report.
    """
    print(f"\n{'='*62}")
    print(f"  BRAIN OPTIMIZER — {symbol}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*62}")

    # ── Stage 1: Wide sweep ──
    combos_s1 = _all_combos(STAGE1_GRID)
    total_s1  = len(combos_s1)

    print(f"\n[STAGE 1] Wide sweep  | {total_s1} combos × {seeds_s1} seeds × {n_ticks_s1} ticks")
    ticks_s1 = [generate_ticks(n_ticks_s1, symbol, seed=s) for s in range(seeds_s1)]

    results = []
    t0 = time.time()
    for i, params in enumerate(combos_s1):
        score = _score_params(symbol, ticks_s1, params)
        results.append((score, params))
        if (i + 1) % 300 == 0 or (i + 1) == total_s1:
            elapsed = time.time() - t0
            pct     = (i + 1) / total_s1 * 100
            eta     = elapsed / (i + 1) * (total_s1 - i - 1)
            print(f"  {i+1:>5}/{total_s1}  ({pct:.0f}%)  ETA {eta:.0f}s  "
                  f"best so far: {max(r[0] for r in results):.2f}")

    results.sort(key=lambda x: x[0], reverse=True)
    top_params = [p for _, p in results[:top_n]]
    print(f"\n  Stage 1 done. Best: {results[0][0]:.2f}  "
          f"| Top-{top_n} advancing to deep validation…")

    # ── Stage 2: Deep validation of top-N only (no new grid explosion) ──
    print(f"\n[STAGE 2] Deep valid  | {top_n} candidates × {seeds_s2} seeds × {n_ticks_s2} ticks")
    ticks_s2 = [generate_ticks(n_ticks_s2, symbol, seed=200 + s) for s in range(seeds_s2)]

    results2 = []
    for i, params in enumerate(top_params):
        score = _score_params(symbol, ticks_s2, params)
        results2.append((score, params))
        print(f"  Candidate {i+1:>2}/{top_n}  score: {score:.2f}")

    results2.sort(key=lambda x: x[0], reverse=True)
    best_score, best_params = results2[0]

    # Full detailed report on the winner
    all_trades = []
    for ticks in ticks_s2:
        all_trades.extend(run_backtest(symbol, ticks, best_params))
    ev = StrategyEvaluator(all_trades)
    report = ev.full_report()

    return {
        "symbol":      symbol,
        "score":       best_score,
        "params":      best_params,
        "report":      report,
        "stage1_best": results[0][0],
        "all_stage2":  [(s, p) for s, p in results2[:10]]
    }


# ─────────────────────────────────────────────
#  CONFIG WRITER
# ─────────────────────────────────────────────

def apply_params_to_config(params: dict, symbol: str):
    """
    Writes the optimized parameters back into config.py in-place,
    replacing only the values that the optimizer controls.
    """
    config_path = os.path.join(os.path.dirname(__file__), "config.py")
    with open(config_path, "r") as f:
        lines = f.readlines()

    replacements = {
        "SPIKE_THRESHOLD_FACTOR": params["spike_threshold"],
        "RSI_OVERSOLD":           params["rsi_oversold"],
        "RSI_OVERBOUGHT":         params["rsi_overbought"],
        "SQUEEZE_THRESHOLD":      params["squeeze_threshold"],
        "ZSCORE_ENTRY":           params["zscore_entry"],
        "BOOM_EXIT_TICKS":        params["exit_ticks"],
        "CRASH_EXIT_TICKS":       params["exit_ticks"],
        "STOP_LOSS_POINTS":       params["stop_loss_points"],
        "TAKE_PROFIT_POINTS":     params["take_profit_points"],
    }

    new_lines = []
    for line in lines:
        written = False
        for key, val in replacements.items():
            if line.strip().startswith(key + " "):
                # Preserve the comment if any
                comment = ""
                if "#" in line:
                    comment = "  " + line[line.index("#"):]
                else:
                    comment = "\n"
                new_lines.append(f"{key} = {val}{comment if comment.endswith(chr(10)) else comment + chr(10)}")
                written = True
                break
        if not written:
            new_lines.append(line)

    with open(config_path, "w") as f:
        f.writelines(new_lines)

    print(f"\n[CONFIG] config.py updated with optimized parameters.")


def save_optimization_report(result: dict):
    """Saves the full optimization report to logs/optimization_report.json."""
    os.makedirs("logs", exist_ok=True)
    path = "logs/optimization_report.json"
    report_data = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": result["symbol"],
        "best_score": result["score"],
        "best_params": result["params"],
        "performance_report": result["report"],
        "top10_stage2": [
            {"rank": i+1, "score": round(s, 2), "params": p}
            for i, (s, p) in enumerate(result["all_stage2"])
        ]
    }
    with open(path, "w") as f:
        json.dump(report_data, f, indent=4)
    print(f"[REPORT] Full report saved → {path}")


# ─────────────────────────────────────────────
#  MAIN
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
    print(f"\n  PERFORMANCE METRICS:")
    print(f"    Trades        : {rep['total_trades']}")
    print(f"    Win Rate      : {rep['win_rate']*100:.1f}%")
    print(f"    Net Profit    : ${rep['net_profit']:+.2f}")
    print(f"    Profit Factor : {rep['profit_factor']:.2f}x")
    print(f"    Max Drawdown  : ${rep['max_drawdown']:.2f}")
    print(f"    Spike Catches : {rep['spike_capture_ratio']*100:.1f}%")
    print(f"    Timeout Ratio : {rep['timeout_ratio']*100:.1f}%")
    print(f"    Max Loss Streak: {rep['loss_streak']} trades")

    print(f"\n  OPTIMAL PARAMETERS:")
    print(f"    Spike Threshold  : {params['spike_threshold']}")
    print(f"    RSI Oversold     : {params['rsi_oversold']}")
    print(f"    RSI Overbought   : {params['rsi_overbought']}")
    print(f"    Squeeze Threshold: {params['squeeze_threshold']}")
    print(f"    Z-Score Entry    : {params['zscore_entry']}")
    print(f"    Exit Ticks       : {params['exit_ticks']}")
    print(f"    Stop Loss (pts)  : {params['stop_loss_points']}")
    print(f"    Take Profit (pts): {params['take_profit_points']}")

    print(f"\n  TOP 5 ALTERNATIVES:")
    for i, (s, p) in enumerate(result["all_stage2"][:5]):
        print(f"    #{i+1}  Score {s:.2f} | SL={p['stop_loss_points']} "
              f"TP={p['take_profit_points']} Exit={p['exit_ticks']} "
              f"RSI<{p['rsi_oversold']}")
    print()


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
        ans = input(f"  Apply these parameters to config.py? [y/N]: ").strip().lower()
        if ans == "y":
            apply_params_to_config(result["params"], symbol)
            print("\n[DONE] Brain update applied. Restart the bot to use new params.")
        else:
            print("\n[SKIP] config.py unchanged. Report saved to logs/.")
