# backtester.py
"""
Parameter Optimizer & Backtesting Engine — v3 (Probability Scoring Model)
Generates synthetic BOOM/CRASH tick data, runs a grid search across strategy
parameters, scores every combination, and writes the best set to config.py.

v3 changes:
  - run_backtest() now uses ml_features.extract_all_features() instead of its
    own inline _extract_features(). Eliminates live/backtest feature divergence
    that caused optimized params to target a ghost version of the strategy.
  - Entry logic replaced with the probability scoring model from strategy.py v3.
    Old RSI/z-score/elif cascade removed — parameters with zero statistical edge.
  - Grid definitions trimmed: rsi_oversold, rsi_overbought, zscore_entry removed.
    entry_score_threshold, weight_cycle added as sweep-able params.

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

import ml_features
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
    is_boom = "BOOM" in sym

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
#  CYCLE STATE HELPER
# ─────────────────────────────────────────────

def _cycle_state(ticks_since_spike: int, cycle_len: int,
                 early: float, hot: float, max_scale: float) -> tuple:
    """
    Returns (zone, lot_scale) for the current cycle position.
    Mirrors strategy.py's _compute_cycle_state() logic exactly.
    """
    pos = ticks_since_spike / cycle_len

    if pos < early:
        return "RECOVERY", 1.0

    elif pos < hot:
        return "BUILDING", 1.0

    elif pos < 1.0:
        progress  = (pos - hot) / (1.0 - hot)
        lot_scale = 1.0 + progress * (max_scale - 1.0)
        return "HOT", round(min(lot_scale, max_scale), 3)

    else:
        return "OVERDUE", round(min(max_scale, max_scale), 3)


# ─────────────────────────────────────────────
#  INLINE BACKTESTER  (fully aligned with strategy.py v3)
# ─────────────────────────────────────────────

def run_backtest(symbol: str, ticks: list, params: dict) -> list:
    """
    Full paper-trading simulation using the v3 probability scoring model.

    Alignment guarantee: uses ml_features.extract_all_features() — the same
    function called by the live strategy — so optimized params apply to the
    exact strategy that runs in production.

    Entry logic mirrors strategy.py v3:
      1. RECOVERY zone → block all entries
      2. OVERDUE zone  → enter unconditionally
      3. All other zones: compute score = weight_cycle × cycle_p
                                        + weight_compress × compress_p
                                        + weight_energy   × energy_p
                          enter if score >= entry_score_threshold

    params keys:
        spike_threshold, squeeze_threshold, exit_ticks,
        stop_loss_points, take_profit_points,
        cooldown_ticks, cycle_early_zone, cycle_hot_zone, cycle_max_lot_scale,
        entry_score_threshold, weight_cycle, weight_compression, weight_energy
    """
    is_boom  = "BOOM"  in symbol.upper()
    is_crash = "CRASH" in symbol.upper()

    # ── Base params ───────────────────────────────────────────────────────────
    sp_factor = params["spike_threshold"]
    sq_thresh = params["squeeze_threshold"]
    max_ticks = params["exit_ticks"]
    sl_pts    = params["stop_loss_points"]
    tp_pts    = params["take_profit_points"]

    # ── Scoring params ────────────────────────────────────────────────────────
    entry_thresh   = params.get("entry_score_threshold", config.ENTRY_SCORE_THRESHOLD)
    w_cycle        = params.get("weight_cycle",       config.WEIGHT_CYCLE)
    w_compress     = params.get("weight_compression", config.WEIGHT_COMPRESSION)
    w_energy       = params.get("weight_energy",      config.WEIGHT_ENERGY)

    # ── Cycle params ──────────────────────────────────────────────────────────
    cooldown   = params.get("cooldown_ticks",      config.POST_TRADE_COOLDOWN_TICKS)
    early_zone = params.get("cycle_early_zone",    config.CYCLE_EARLY_ZONE)
    hot_zone   = params.get("cycle_hot_zone",      config.CYCLE_HOT_ZONE)
    max_scale  = params.get("cycle_max_lot_scale", config.CYCLE_MAX_LOT_SCALE)
    cycle_len  = 1000

    # ── State ─────────────────────────────────────────────────────────────────
    window = config.TICK_WINDOW_SIZE
    buf    = []

    direction   = None
    entry_price = None
    ticks_held  = 0
    lot         = 1.0

    ticks_since_last_close = cooldown       # start ready to trade
    ticks_since_spike      = cycle_len // 2  # start at 50% — neutral zone

    trades  = []
    balance = config.INITIAL_BALANCE

    for price in ticks:
        buf.append(price)
        if len(buf) > window * 2:
            buf.pop(0)
        if len(buf) < window:
            continue

        # ── Spike detection ───────────────────────────────────────────────────
        changes  = [abs(buf[i] - buf[i-1]) for i in range(1, len(buf))]
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
            ticks_since_spike = 0

        zone, lot_scale = _cycle_state(
            ticks_since_spike, cycle_len, early_zone, hot_zone, max_scale
        )

        # ── If in a trade: check exit conditions ──────────────────────────────
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
                good = (direction == "BUY"  and last_chg > 0) or \
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
                    "pnl":           round(pnl, 4),
                    "balance":       round(balance, 2),
                    "exit_reason":   exit_reason,
                    "ticks_held":    ticks_held,
                    "spike_detected": spike_cap,
                })
                direction              = None
                entry_price            = None
                ticks_held             = 0
                ticks_since_last_close = 0

            continue   # never open a new trade on the same tick as a close

        # ── Cooldown gate (flat position) ─────────────────────────────────────
        ticks_since_last_close += 1

        # ── RECOVERY: block all entries ───────────────────────────────────────
        if zone == "RECOVERY":
            continue

        # ── Cooldown: wait minimum ticks since last close ─────────────────────
        if ticks_since_last_close < cooldown:
            continue

        # ── Skip spike tick itself (move already happened) ────────────────────
        if is_spike:
            continue

        # ── Compute probability score (mirrors strategy.py v3) ────────────────
        feats = ml_features.extract_all_features(buf, window)

        k       = ticks_since_spike
        cycle_p = 1.0 - (1.0 - 1.0 / cycle_len) ** k
        cycle_p = min(cycle_p, 1.0)

        comp       = feats["compression_ratio"]
        compress_p = max(0.0, (sq_thresh - comp) / sq_thresh)

        recent     = buf[-10:]
        down_ticks = sum(1 for i in range(1, len(recent)) if recent[i] < recent[i-1])
        up_ticks   = len(recent) - 1 - down_ticks
        energy_p   = min(down_ticks / 10.0, 1.0) if is_boom else min(up_ticks / 10.0, 1.0)

        score = (
            w_cycle    * cycle_p    +
            w_compress * compress_p +
            w_energy   * energy_p
        )

        # ── Entry decision ────────────────────────────────────────────────────
        entry_signal = False

        if zone == "OVERDUE":
            entry_signal = True                  # hard trigger
        elif score >= entry_thresh:
            entry_signal = True                  # score threshold met

        if entry_signal:
            direction   = "BUY" if is_boom else "SELL"
            entry_price = price
            ticks_held  = 0
            lot         = lot_scale

    return trades


# ─────────────────────────────────────────────
#  GRID DEFINITIONS  (v3 — RSI/z-score removed)
# ─────────────────────────────────────────────

# Stage 1: Core strategy params (wide sweep, fast)
# RSI, RSI_OVERBOUGHT, ZSCORE_ENTRY removed — audit showed zero predictive power.
STAGE1_GRID = {
    "spike_threshold":      [2.0, 2.5, 3.5],
    "squeeze_threshold":    [0.60, 0.75, 0.90],
    "exit_ticks":           [60, 90, 120],
    "stop_loss_points":     [1.5, 2.5, 4.0],
    "take_profit_points":   [10.0, 15.0, 20.0],
    "entry_score_threshold":[0.35, 0.42, 0.50],
    # Cycle defaults fixed for Stage 1 (swept in Stage 2)
    "cooldown_ticks":       [60],
    "cycle_early_zone":     [0.15],
    "cycle_hot_zone":       [0.60],
    "cycle_max_lot_scale":  [2.5],
    "weight_cycle":         [0.60],
    "weight_compression":   [0.20],
    "weight_energy":        [0.20],
    # Total: 3×3×3×3×3×3 = 729 combos
}

# Stage 2: Cycle & scoring params swept over top-N Stage 1 configs
CYCLE_GRID = {
    "cooldown_ticks":       [40, 60, 80],
    "cycle_early_zone":     [0.10, 0.15, 0.25],
    "cycle_hot_zone":       [0.55, 0.65, 0.75],
    "cycle_max_lot_scale":  [2.0, 2.5, 3.0],
    "weight_cycle":         [0.55, 0.65],
    # Total: 3×3×3×3×2 = 162 cycle combos
}


def _all_combos(grid: dict) -> list:
    keys   = list(grid.keys())
    values = list(grid.values())
    return [dict(zip(keys, combo)) for combo in itertools.product(*values)]


def _score_params(symbol: str, ticks_sets: list, params: dict) -> float:
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
                n_ticks_s1: int = 4000,
                n_ticks_s2: int = 8000,
                seeds_s1:   int = 3,
                seeds_s2:   int = 5,
                top_n:      int = 5) -> dict:
    """
    Three-stage grid search (v3):

    Stage 1 — Wide base sweep (729 combos, 3 seeds × 4000 ticks each)
               n_ticks_s1 raised from 1,200 → 4,000 so each combo produces
               ~25–50 trades (vs previous 8–15, which was luck-dominated).

    Stage 2 — Cycle + weight sweep (top-N × 162 combos, 5 seeds × 8000 ticks)
               Tests all cycle and weight parameter combinations on long data.

    Stage 3 — Deep validation of the single overall winner on fresh seeds.
    """
    print(f"\n{'='*62}")
    print(f"  BRAIN OPTIMIZER v3 (Probability Scoring) — {symbol}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*62}")

    # ── Stage 1: Wide base sweep ──────────────────────────────────────────────
    combos_s1 = _all_combos(STAGE1_GRID)
    total_s1  = len(combos_s1)
    ticks_s1  = [generate_ticks(n_ticks_s1, symbol, seed=s) for s in range(seeds_s1)]

    print(f"\n[STAGE 1] Base sweep   | {total_s1} combos × {seeds_s1} seeds × {n_ticks_s1} ticks")
    print(f"          (increased from 1200 → {n_ticks_s1} ticks to ensure ≥25 trades/combo)")

    results_s1 = []
    t0 = time.time()
    for i, params in enumerate(combos_s1):
        score = _score_params(symbol, ticks_s1, params)
        results_s1.append((score, params))
        if (i + 1) % 100 == 0 or (i + 1) == total_s1:
            elapsed = time.time() - t0
            pct     = (i + 1) / total_s1 * 100
            eta     = elapsed / (i + 1) * (total_s1 - i - 1)
            print(f"  {i+1:>5}/{total_s1}  ({pct:.0f}%)  ETA {eta:.0f}s  "
                  f"best so far: {max(r[0] for r in results_s1):.2f}")

    results_s1.sort(key=lambda x: x[0], reverse=True)
    top_base = [p for _, p in results_s1[:top_n]]
    print(f"\n  Stage 1 done. Best: {results_s1[0][0]:.2f} | "
          f"Top-{top_n} advancing to cycle sweep…")

    # ── Stage 2: Cycle + weight param sweep over top-N base configs ───────────
    cycle_combos = _all_combos(CYCLE_GRID)
    n_s2         = len(top_base) * len(cycle_combos)
    ticks_s2     = [generate_ticks(n_ticks_s2, symbol, seed=200 + s) for s in range(seeds_s2)]

    print(f"\n[STAGE 2] Cycle sweep  | {top_n} base × {len(cycle_combos)} cycle "
          f"= {n_s2} combos × {seeds_s2} seeds × {n_ticks_s2} ticks")

    results_s2 = []
    t0          = time.time()
    counter     = 0
    for base in top_base:
        for cyc in cycle_combos:
            params = {**base, **cyc}
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

    # ── Stage 3: Deep validation of the overall winner ────────────────────────
    print(f"\n[STAGE 3] Final valid  | 1 winner × 8 seeds × {n_ticks_s2} ticks")
    ticks_s3   = [generate_ticks(n_ticks_s2, symbol, seed=500 + s) for s in range(8)]
    all_trades = []
    for ticks in ticks_s3:
        all_trades.extend(run_backtest(symbol, ticks, best_params))

    ev          = StrategyEvaluator(all_trades)
    report      = ev.full_report()
    final_score = ev.strategy_score()
    print(f"  Final validated score: {final_score:.2f}")

    return {
        "symbol":      symbol,
        "score":       final_score,
        "params":      best_params,
        "report":      report,
        "stage1_best": results_s1[0][0],
        "stage2_best": best_score_s2,
        "all_stage2":  [(s, p) for s, p in results_s2[:10]],
    }


# ─────────────────────────────────────────────
#  CONFIG WRITER
# ─────────────────────────────────────────────

def apply_params_to_config(params: dict, symbol: str):
    """Writes optimized parameters back into config.py in-place."""
    config_path = os.path.join(os.path.dirname(__file__), "config.py")
    with open(config_path, "r") as f:
        lines = f.readlines()

    replacements = {
        "SPIKE_THRESHOLD_FACTOR":   params["spike_threshold"],
        "SQUEEZE_THRESHOLD":        params["squeeze_threshold"],
        "BOOM_EXIT_TICKS":          params["exit_ticks"],
        "CRASH_EXIT_TICKS":         params["exit_ticks"],
        "STOP_LOSS_POINTS":         params["stop_loss_points"],
        "TAKE_PROFIT_POINTS":       params["take_profit_points"],
        "ENTRY_SCORE_THRESHOLD":    params.get("entry_score_threshold", config.ENTRY_SCORE_THRESHOLD),
        "WEIGHT_CYCLE":             params.get("weight_cycle",          config.WEIGHT_CYCLE),
        "WEIGHT_COMPRESSION":       params.get("weight_compression",    config.WEIGHT_COMPRESSION),
        "WEIGHT_ENERGY":            params.get("weight_energy",         config.WEIGHT_ENERGY),
        "POST_TRADE_COOLDOWN_TICKS": params.get("cooldown_ticks",       config.POST_TRADE_COOLDOWN_TICKS),
        "CYCLE_EARLY_ZONE":         params.get("cycle_early_zone",      config.CYCLE_EARLY_ZONE),
        "CYCLE_HOT_ZONE":           params.get("cycle_hot_zone",        config.CYCLE_HOT_ZONE),
        "CYCLE_MAX_LOT_SCALE":      params.get("cycle_max_lot_scale",   config.CYCLE_MAX_LOT_SCALE),
    }

    new_lines = []
    for line in lines:
        written = False
        for key, val in replacements.items():
            if line.strip().startswith(key + " ") or line.strip().startswith(key + "="):
                indent  = len(line) - len(line.lstrip())
                comment = f"  # optimized {datetime.now().strftime('%Y-%m-%d')}"
                if isinstance(val, float) and val == int(val):
                    new_lines.append(f"{' '*indent}{key} = {val}{comment}\n")
                elif isinstance(val, float):
                    new_lines.append(f"{' '*indent}{key} = {round(val, 4)}{comment}\n")
                else:
                    new_lines.append(f"{' '*indent}{key} = {val}{comment}\n")
                written = True
                break
        if not written:
            new_lines.append(line)

    with open(config_path, "w") as f:
        f.writelines(new_lines)

    print(f"\n[CONFIG] Params written to config.py for {symbol}:")
    for k, v in replacements.items():
        print(f"  {k:<28} = {v}")


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    symbol     = sys.argv[1] if len(sys.argv) > 1 else config.ACTIVE_SYMBOL
    auto_apply = "--apply" in sys.argv

    result = grid_search(symbol)

    print(f"\n{'='*62}")
    print(f"  FINAL RESULT — {symbol}")
    print(f"{'='*62}")
    print(f"  Stage 1 score : {result['stage1_best']:.2f}")
    print(f"  Stage 2 score : {result['stage2_best']:.2f}")
    print(f"  Stage 3 score : {result['score']:.2f}  ← validated on fresh seeds")
    print(f"\n  Trade report  :")
    for k, v in result["report"].items():
        print(f"    {k:<24} {v}")

    print(f"\n  Best params:")
    for k, v in result["params"].items():
        print(f"    {k:<28} {v}")

    # Save full report to logs/
    os.makedirs("logs", exist_ok=True)
    report_path = os.path.join("logs", "optimization_report.json")
    with open(report_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\n  Full report saved → {report_path}")

    if auto_apply:
        apply_params_to_config(result["params"], symbol)
    else:
        ans = input("\n  Apply these params to config.py? [y/N] ").strip().lower()
        if ans == "y":
            apply_params_to_config(result["params"], symbol)
        else:
            print("  Params NOT applied. config.py unchanged.")
