# AI-Assisted Synth Index Spike Agent — Project Handoff
**Last updated:** 2026-06-04 (Change 010 — Probability Scoring Model + Critical Bug Fixes)  
**Maintained by:** Replit AI Agent  
**Purpose:** This file is the complete change log and context document. If you are a new AI agent picking up this project, READ THIS FIRST before touching any code.

---

## 1. What This Project Is

A Python CLI trading bot that connects to the **Deriv WebSocket API** and trades synthetic indices — specifically **BOOM1000** (and optionally CRASH1000/500). It is a **paper-trading** (simulated, no real money) system.

The owner has built an **Android app** (Samsung A21s) that uses these Python scripts as its "brain". The workflow is:
- Tune/optimize scripts here (on Replit or any PC)
- Package the updated `.py` files and push them to the Android app
- The app loads the new scripts = a **"brain update"**

So every change here is essentially a firmware upgrade for the Android trading app.

---

## 2. Project File Map

```
/
├── main.py              — Bot orchestrator. Starts WebSocket stream, calls strategy, loops.
├── config.py            — ALL tunable parameters live here. THE file to change for a brain update.
├── data_stream.py       — Deriv WebSocket connection + simulated tick fallback.
├── strategy.py          — Entry signal logic (RSI, squeeze, Z-score, EMA slope, momentum).
├── ml_features.py       — Technical indicator calculations (SMA, EMA, RSI, Z-score, std-dev).
├── trader.py            — Paper trade execution: open/close positions, PnL, stop-loss, TP.
├── risk_manager.py      — Guards: cooldown, max daily loss, drawdown protection.
├── logger.py            — Writes trades to logs/trade_log.csv and logs/trade_log.json.
├── backtester.py        — Parameter optimizer. Run: python backtester.py BOOM1000 --apply
├── evaluator.py         — Composite scoring engine used by backtester (no external deps).
├── download_history.py  — (Untouched) Historical tick downloader utility.
├── requirements.txt     — Only dependency: websocket-client==1.6.1
├── logs/
│   ├── trade_log.csv           — Every closed trade (live bot writes here)
│   ├── trade_log.json          — Same trades in JSON
│   ├── bot_metrics.json        — Rolling session stats (win rate, net profit, drawdown)
│   └── optimization_report.json — Last backtester run results
└── _handoff/
    └── PROJECT_HANDOFF.md      — This file
```

---

## 3. Complete Change Log

### CHANGE 001 — Fixed Deriv WebSocket Symbol Mapping
**File:** `data_stream.py`  
**Problem:** Bot was connecting but immediately erroring with `Symbol R_BOOM1000 is invalid`. The original code was prepending `R_` to symbol names (e.g. BOOM1000 → R_BOOM1000), but Deriv's API no longer uses the `R_` prefix for these symbols.  
**Fix:** Removed the `R_` prefix logic entirely. Symbol is now used as-is from config.  
**Before:**
```python
if "R_" not in self.raw_symbol:
    self.symbol = f"R_{self.raw_symbol}" if self.raw_symbol in [...] else self.raw_symbol
```
**After:**
```python
self.symbol = self.raw_symbol
```
**Status:** Confirmed working. Bot connects and receives live BOOM1000 ticks.

---

### CHANGE 002 — Complete config.py Rewrite (Strategy Parameters)
**File:** `config.py`  
**Problem:** Original config had parameters that guaranteed losses:
- `BOOM_EXIT_TICKS = 10` — Exiting after 10 ticks on a market that spikes every ~1000 ticks = near-certain loss every trade.
- `COOLDOWN_AFTER_LOSS_STREAK = 3` with `COOLDOWN_MINUTES = 30` — After only 3 losses the bot locked itself out for 30 minutes.
- `SPIKE_THRESHOLD_FACTOR = 4.5` — Too high, missed real spikes.
- No stop-loss or take-profit existed.

**New parameters added:**
```python
STOP_LOSS_POINTS = 4.0        # Exit if price moves 4 pts against us (was: None)
TAKE_PROFIT_POINTS = 20.0     # Lock in profit at 20 pts gain (was: None)
RSI_OVERSOLD = 35             # Was hardcoded 30 inside strategy.py
RSI_OVERBOUGHT = 58           # Was hardcoded 70 inside strategy.py
SQUEEZE_THRESHOLD = 0.75      # Was hardcoded 0.75 inside strategy.py
ZSCORE_ENTRY = 0.8            # Was hardcoded 1.2 inside strategy.py
```

**Key value changes (before → after):**
| Parameter | Before | After | Reason |
|---|---|---|---|
| BOOM_EXIT_TICKS | 10 | 120 | Give spike more time to occur |
| COOLDOWN_AFTER_LOSS_STREAK | 3 | 5 | Less aggressive lockout |
| COOLDOWN_MINUTES | 30 | 3 | Brief pause not a session killer |
| SPIKE_THRESHOLD_FACTOR | 4.5 | 3.0 | Catch real spikes more reliably |
| MAX_TRADES_PER_SESSION | 20 | 50 | Allow more trading |
| MAX_DRAWDOWN_PCT | 0.10 | 0.15 | More breathing room |

---

### CHANGE 003 — strategy.py Rewrite (Entry Logic)
**File:** `strategy.py`  
**Problem:** Three issues:
1. All thresholds were hardcoded — couldn't be tuned from config.
2. Entry conditions were too restrictive (RSI < 30 is very rare on BOOM1000).
3. Missing a 4th entry signal: "energy build-up" (8+ consecutive down-ticks = spring coiling).

**What changed:**
- All thresholds now read from `config.py` (RSI_OVERSOLD, SQUEEZE_THRESHOLD, ZSCORE_ENTRY).
- Added **Signal D**: "8 of last 10 ticks are down AND market is squeezed" = buy. This is BOOM-specific — consecutive down-ticks build energy for the next spike.
- Relaxed `micro_spike_warning` threshold from `0.8` to `0.6` (less strict).
- Relaxed slope check from `slope > 0` to `slope >= -0.005` (allows flat slope).
- Added `recent_down_ticks` / `recent_up_ticks` counters to analytics output.

**Entry signals for BOOM (priority order):**
1. RSI < 35 (oversold mean-reversion)
2. Squeeze + Z-score < -0.8 + flat/positive slope
3. Momentum + positive slope + micro-volatility expanding
4. 8/10 recent ticks down + squeeze active (energy build-up)

---

### CHANGE 004 — trader.py Rewrite (Exit Logic + Stop Loss)
**File:** `trader.py`  
**Problem:** No stop-loss or take-profit. Only two exit conditions existed: spike captured OR tick timeout. This meant losing trades could bleed the full drift loss over 10 ticks.

**New exit rules (in priority order):**
1. **Stop-loss:** `pnl <= -STOP_LOSS_POINTS * lot_size` → exit immediately
2. **Take-profit:** `pnl >= TAKE_PROFIT_POINTS * lot_size` → lock in gain
3. **Spike captured:** spike in correct direction → exit at peak
4. **Adverse spike:** spike in wrong direction and PnL negative → cut loss
5. **Tick timeout:** held `BOOM_EXIT_TICKS` ticks without any of the above

**Also improved:**
- `_close_trade()` separated into its own method (cleaner code).
- Trade close log now shows: direction, entry/exit price, PnL, ticks held, reason, balance, win rate.
- Tracks `peak_pnl` per trade for diagnostics.

---

### CHANGE 005 — evaluator.py Rewrite (Removed pandas dependency)
**File:** `evaluator.py`  
**Problem:** The file imported `pandas` which is not installed (and not needed). This would crash any code that imported evaluator.  
**Fix:** Removed `import pandas as pd`. All logic already used pure Python dicts/lists.  
**Also:** Updated all metric keys to match actual trade log format (`pnl` not `profit`, `ticks_held` not `duration`).  
**Added:** `spike_capture_ratio()` metric — percentage of wins that were actual spike captures.

---

### CHANGE 006 — backtester.py Full Rewrite (Parameter Optimizer)
**File:** `backtester.py`  
**Problem:** Original only optimized one parameter (spike_threshold), required CSV files that didn't exist, and had no scoring system.

**New capabilities:**
- **Synthetic tick generator** — `generate_ticks(n, symbol, seed)` produces realistic BOOM/CRASH price series with correct physics (downward drift + spikes at correct frequency).
- **Inline fast backtest** — `run_backtest(symbol, ticks, params)` runs a full simulation without touching config.py, so multiple parameter sets can be tested in parallel without side effects.
- **2-stage grid search:**
  - Stage 1: 2,916 combos × 2 seeds × 1,200 ticks (~75 seconds)
  - Stage 2: Top-10 from Stage 1 × 5 seeds × 8,000 ticks (~15 seconds)
- **Composite scorer** via `StrategyEvaluator` — weights win rate (40pts), profit factor (25pts), net profit (15pts), drawdown (-15pts), timeout ratio (-10pts), spike captures (+5pts).
- **Auto-writes winner to config.py** when `--apply` flag is used.
- **Saves full report** to `logs/optimization_report.json`.

**How to run:**
```bash
python backtester.py                   # optimize BOOM1000, asks before applying
python backtester.py CRASH1000         # optimize a different symbol
python backtester.py BOOM1000 --apply  # run + auto-apply without prompt
```

---

### CHANGE 007 — Spike Cycle Counter
**Files:** `config.py`, `strategy.py`, `trader.py`, `main.py`  
**Problem:** The strategy had no awareness of *when* the last spike occurred. It treated every tick identically, ignoring the most important statistical edge available: BOOM1000 fires roughly 1 spike per 1000 ticks, so a position entered at tick 900-since-last-spike has ~3× the spike probability of one entered at tick 100.

**What was built:**

`config.py` — 5 new parameters:
```python
SPIKE_CYCLE_LENGTH = 1000    # expected ticks between spikes
CYCLE_EARLY_ZONE   = 0.25    # 0–25% of cycle: RECOVERY, no entries
CYCLE_HOT_ZONE     = 0.70    # 70–100% of cycle: HOT, relaxed thresholds
CYCLE_LOT_SCALING  = True    # enable dynamic lot sizing
CYCLE_MAX_LOT_SCALE= 2.0     # max lot multiplier (at OVERDUE)
```

`strategy.py` — `SpikeStrategy` gains:
- `ticks_since_last_spike` counter (starts at 500 = neutral BUILDING zone on startup)
- `total_spikes_observed` counter (session stat)
- `_compute_cycle_state()` → returns `(multiplier, zone_label)`
- **4 zones with different behaviour:**

| Zone | Ticks since spike | Multiplier | Bot behaviour |
|---|---|---|---|
| RECOVERY | 0–250 | 0.10–0.50 | All entries blocked |
| BUILDING | 250–700 | 0.50–1.00 | Normal signals apply |
| HOT | 700–1000 | 1.00–1.75 | RSI+Z-score thresholds relaxed by ~10% |
| OVERDUE | 1000+ | 1.75–2.00 | Signal E fires: enter without other confirmation |

- **When a spike is detected mid-analysis:** counter resets to 0, decision forced to HOLD (the spike is already done, no point entering), zone immediately becomes RECOVERY.
- **All entry reasons now include zone + tick count** in the log string for easy debugging.

`trader.py` — lot sizing is now dynamic:
```python
lot_size = config.DEFAULT_LOT_SIZE * analytics.get("cycle_lot_scale", 1.0)
```
In OVERDUE zone with 2.0x scale: a standard 1.0-lot trade becomes 2.0 lots, doubling profit on the spike capture that's statistically imminent.

`main.py` — console output now shows the full cycle state per tick:
```
[#  355] Price: 14131.2  RSI: 0.0  Sqz: 0.14  Cycle: 805tk/80% [HOT] 1.38x lots:1.38  Pos: BUY x1.38
```

**Verified working:** Unit test confirmed all 4 zones produce correct multipliers. Bot is live on BOOM1000 with cycle counter active.

---

### CHANGE 008 — Bug Fixes: RSI Signal + Post-Trade Cooldown
**Files:** `strategy.py`, `trader.py`, `config.py`

**Bug 1 — RSI always 0.0 (always firing Signal A):**
BOOM1000 drifts DOWN ~0.07/tick between every spike. In a pure downtrend, avg_gain = 0 → RSI = 0. Since `RSI_OVERSOLD = 35`, the check `0 < 35` was always True, so the bot entered a BUY immediately every time warmup finished — regardless of market conditions.

**Fix:** Signal A now requires a secondary condition:
```python
# Before (broken):
if features["rsi"] < rsi_threshold:

# After (fixed):
if features["rsi"] < rsi_threshold and (is_squeezed or down_ticks >= 6):
```
This prevents entering just because BOOM1000 is in its natural drift. Requires compression OR strong directional momentum as confirmation.

**Bug 2 — Immediate re-entry after every trade close:**
After a timeout loss, `active_trade` was set to `None` and the very next tick re-entered. This created a "loss → 1 tick wait → loss" death loop.

**Fix:** `POST_TRADE_COOLDOWN_TICKS = 60` added to config. `trader.py` tracks `ticks_since_last_close` and blocks all entries until the counter reaches the threshold. Counter resets to 0 on close, starts at `POST_TRADE_COOLDOWN_TICKS` at startup (so first entry is immediate).

---

### CHANGE 009 — Optimizer v2 (Cycle-Aware 3-Stage Grid Search)
**Files:** `backtester.py`

**What changed:**
- `run_backtest()` now simulates ALL live logic: Signal A fix, cooldown, spike cycle counter, RECOVERY zone blocking, HOT/OVERDUE lot scaling, Signal E unconditional entry in OVERDUE
- 3-stage grid search:
  - **Stage 1** (972 combos, 2 seeds, 1200 ticks): finds best base params fast
  - **Stage 2** (top-5 base × 81 cycle combos, 5 seeds, 8000 ticks): sweeps all cycle parameter combinations
  - **Stage 3** (winner × 8 fresh seeds, 8000 ticks): final validation
- `apply_params_to_config()` now writes ALL 13 parameters including the 4 new cycle params

**Result of run on 2026-06-04:**

| Metric | Value |
|---|---|
| Stage 1 best score | 64.34 |
| Stage 2 best score | 59.75 |
| Stage 3 final score | 47.70 |
| Trades | 207 |
| Win Rate | 13.5% |
| Spike Captures | 45.9% |
| Max Drawdown | $204.57 |

**Optimal parameters applied to config.py:**

```python
# Base params
SPIKE_THRESHOLD_FACTOR = 2.5
RSI_OVERSOLD           = 28
SQUEEZE_THRESHOLD      = 0.75
ZSCORE_ENTRY           = 0.8
BOOM_EXIT_TICKS        = 120
STOP_LOSS_POINTS       = 2.5
TAKE_PROFIT_POINTS     = 20.0

# Cycle params (new)
POST_TRADE_COOLDOWN_TICKS = 60     # wait 60 ticks between trades
CYCLE_EARLY_ZONE          = 0.15   # RECOVERY ends at 150 ticks
CYCLE_HOT_ZONE            = 0.60   # HOT begins at 600 ticks (earlier than before)
CYCLE_MAX_LOT_SCALE       = 2.5    # max 2.5x lot in OVERDUE
```

**Key insight:** HOT zone now starts at 600 ticks (was 700). The optimizer found that being aggressive earlier in the cycle — when the spike is only 60% expected — is more profitable than waiting until 70%. Cooldown increased to 60 ticks (was 40) to reduce the frequency of losing trades.

---

### CHANGE 010 — Probability Scoring Model + Four Critical Bug Fixes
**Date:** 2026-06-04  
**Files:** `strategy.py`, `ml_features.py`, `evaluator.py`, `backtester.py`, `config.py`

This is the most significant architectural change to date. Driven by the full quantitative audit (audit.py), which proved that RSI, compression, z-score, momentum, and down-ticks all have zero statistically significant predictive power for upcoming spikes (r_pb ≈ 0, p > 0.05 on 250,000 ticks). The only real edge is the spike cycle counter.

---

#### Bug Fix A — EMA Gradient 1-Tick Stale (`ml_features.py`)

**Root cause:** `calculate_ema_gradient()` used `for i in range(3, 0, -1)` with a dead `else prices` branch. Since `i` is always > 0, the "current" EMA was computed on `prices[:-1]` — one tick behind. Signals B and C in the old strategy gated on `ema_slope`, meaning they were making decisions based on stale slope data.

**Fix:** Replaced loop with three explicit slices:
```python
ema_two_ago = calculate_ema(prices[:-2], window)
ema_one_ago = calculate_ema(prices[:-1], window)  # unused but illustrative
ema_current = calculate_ema(prices,      window)  # now actually current
slope = (ema_current - ema_two_ago) / 2.0
```

---

#### Bug Fix B — Live vs Backtest Feature Divergence (`backtester.py`)

**Root cause:** `strategy.py` called `ml_features.extract_all_features()`, but `backtester.py` had its own inline `_extract_features()` function with a different EMA slope implementation. This meant the optimizer was tuning a ghost version of the strategy that didn't match what ran live. Parameters selected by the optimizer applied to the wrong EMA behavior.

**Fix:** Removed all backtester inline math helpers (`_calc_sma`, `_calc_std`, `_calc_rsi`, `_calc_ema`, `_ema_slope`, `_extract_features`). `backtester.py` now calls `ml_features.extract_all_features()` directly — the identical code path used by the live strategy. Live and backtest are now guaranteed to compute the same features.

---

#### Bug Fix C — Evaluator Score Stuck Near 50 (`evaluator.py`)

**Root cause:** The scoring formula added a 50-point base: `return 50 + raw`. With typical BOOM1000 stats (WR=13.5%, PF=0.8), the raw component was only ±5 points. This meant ALL parameter combinations scored between 45–55 — the optimizer was searching through noise, unable to distinguish good from bad parameters. The 26% score drop from Stage 1 to Stage 3 was partly a symptom of this.

**Fix:** Removed the 50-point base entirely. Recalibrated normalisation constants so the range matches realistic achievable values on an 8,000-tick run:

| Component | v1 (broken) | v2 (fixed) |
|---|---|---|
| Win Rate | `wr × 40` | `min(wr/0.30, 1) × 50` |
| Profit Factor | `min(pf/5,1) × 25` | `min(pf/3.0, 1) × 25` |
| Net Profit | `±1.0 → ±15 (norm ÷500)` | `±1.0 → ±15 (norm ÷150)` |
| Max Drawdown | `−(dd÷500) × 15` | `−(dd÷300) × 15` |
| Timeout ratio | `−to × 10` | `−to × 15` |
| Spike captures | `sc × 5` | `sc × 10` |
| **Base offset** | **+50 (REMOVED)** | **None** |

Random-entry strategy now scores ~8–12 (was ~50). Good cycle strategy scores ~45–65 (was ~52).

---

#### Bug Fix D — RSI/Z-Score Removed from Optimizer Grid (`backtester.py`)

**Root cause:** `rsi_oversold`, `rsi_overbought`, and `zscore_entry` were in the Stage 1 grid despite the audit proving they have zero predictive power. The optimizer wasted compute sweeping parameters that contributed nothing, and was creating false "best configurations" that happened to luck into a particular RSI value.

**Fix:** Removed `rsi_oversold`, `rsi_overbought`, `zscore_entry` from all grid definitions. Added `entry_score_threshold` and `weight_cycle` as sweepable params instead. Also raised Stage 1 minimum ticks from 1,200 → 4,000 to ensure ≥25 trades per combo (was 8–15, which was luck-dominated).

---

#### New Feature — Probability Scoring Model (`strategy.py` v3)

Replaces the 5-signal `if/elif` cascade with a continuous weighted score.

**Why the old cascade was bad:**
- `elif` ordering: Signal A almost always fired first (RSI≈0 on BOOM1000 = always true), hiding Signals B–E
- Signal E (OVERDUE — unconditional, only valid signal) was blocked by Signal A
- Binary BUY/HOLD output lost signal strength information

**New model:**
```python
# Geometric probability of spike on this tick
cycle_p    = 1.0 - (1.0 - 1/1000) ** ticks_since_spike

# Volatility compression (unproven — low weight)
compress_p = max(0, (SQUEEZE_THRESHOLD - compression_ratio) / SQUEEZE_THRESHOLD)

# Directional energy (unproven — low weight)  
energy_p   = min(down_ticks / 10.0, 1.0)   # BOOM; up_ticks for CRASH

# Weighted composite
score = WEIGHT_CYCLE × cycle_p        # 0.60 — proven
      + WEIGHT_COMPRESSION × compress_p   # 0.20 — unproven
      + WEIGHT_ENERGY × energy_p          # 0.20 — unproven

# confidence = how much of the score is cycle-driven (vs unproven signals)
confidence = (WEIGHT_CYCLE × cycle_p) / score
```

**Entry rules (replaces all 5 signals):**
| Zone | Rule |
|---|---|
| RECOVERY | Hard block — always HOLD |
| BUILDING | Enter if `score >= ENTRY_SCORE_THRESHOLD (0.42)` |
| HOT | Enter if `score >= ENTRY_SCORE_THRESHOLD (0.42)` |
| OVERDUE | Hard trigger — always BUY/SELL |

**New analytics output (visible in logs):**
```
Score 51.3% ≥ 42% threshold | Cycle 847tk (56.8%) Compress 80% Energy 70% [HOT] Conf 66%
```

**New config params added:**
```python
ENTRY_SCORE_THRESHOLD = 0.42   # minimum score to open a trade
WEIGHT_CYCLE          = 0.60   # proven predictor
WEIGHT_COMPRESSION    = 0.20   # unproven — keep small
WEIGHT_ENERGY         = 0.20   # unproven — keep small
```

---

#### Impact Summary

| Metric | Before (v2) | After (v3) |
|---|---|---|
| Active signals | 5 (RSI, squeeze, momentum, energy, OVERDUE) | 3 components in single weighted score |
| Signal ordering problem | Yes (elif hides OVERDUE behind RSI) | No (all evaluated simultaneously) |
| EMA slope accuracy | 1 tick stale | Current tick (fixed) |
| Backtest/live alignment | Divergent (different EMA code) | Identical (shared ml_features module) |
| Score range for optimizer | 45–55 (near-constant, noise) | 0–100 (calibrated, meaningful) |
| Optimizer grid size | 3,321 combos × 8–15 trades | 729 combos × 25–50 trades |
| RSI in optimizer grid | Yes (waste — zero predictive power) | Removed |
| Confidence score | Not computed | Output on every tick |

**Full update payload for Android brain update:**
`config.py` + `strategy.py` + `ml_features.py` + `evaluator.py` + `backtester.py`

---

## 4. Optimization Results (First Run — 2026-06-03)

**Symbol:** BOOM1000  
**Best score:** 31.69 / 100  
**Key finding:** No parameter combination in a 2,916-combo grid could achieve a positive-expectancy strategy using simple RSI/squeeze/momentum rules alone.

**Why this is expected (important math):**
- BOOM1000 fires ~1 spike per 1000 ticks
- With 120-tick hold window: P(spike in window) ≈ 11.3%
- For 13% win rate to be profitable: average win must be >6.5× average loss
- With SL=4pts, TP=20pts: ratio is only 5× — not enough

**Best parameters found (now live in config.py):**
```
spike_threshold   = 3.0
rsi_oversold      = 35
squeeze_threshold = 0.75
zscore_entry      = 0.8
exit_ticks        = 120
stop_loss_points  = 4.0
take_profit_points= 20.0
```

---

## 5. Current Bot Behaviour (as of last run)

- Connects live to Deriv WebSocket → BOOM1000 real ticks
- Warms up for 50 ticks, then starts analysing
- Enters BUY when: RSI < 35, OR squeeze+z-score, OR momentum burst, OR 8/10 down-ticks+squeeze
- Holds up to 120 ticks
- Exits on: stop-loss (-4 pts), take-profit (+20 pts), spike capture, or timeout
- Logs every trade to `logs/trade_log.csv` and `logs/trade_log.json`
- Risk guard: 5 consecutive losses → 3-min cooldown; daily loss > $50 → session halt

---

## 6. What Was NOT Done Yet (Next Steps)

### NEXT: Spike Cycle Counter (HIGH PRIORITY)
This is the feature most likely to move the needle on profitability.

**Concept:** BOOM1000's spikes are distributed roughly evenly over time. If 900 ticks have passed since the last spike, one is statistically overdue. The bot should:
1. Track the tick count since the last observed spike
2. Compute a "spike probability multiplier" based on position in the 1000-tick cycle
3. Scale entry aggressiveness (and optionally lot size) when deep in the cycle
4. Avoid entering a new trade immediately after a spike (probability resets to low)

**Files to modify:** `strategy.py` (add cycle tracking), `main.py` (pass spike event back to strategy), `config.py` (add SPIKE_CYCLE_LENGTH = 1000)

**This feature is designed but not built. The previous AI agent was about to start it when the user asked for this handoff file to be written first.**

### OTHER IDEAS (Lower priority)
- CRASH500/BOOM500 support (faster spike cycles, higher frequency trading)
- Real Deriv API token integration (live account trading, not just paper)
- Stats dashboard — a simple HTTP endpoint serving `logs/bot_metrics.json` as JSON for the Android app to poll
- Tick pattern ML — use actual historical Deriv tick CSVs to train a pattern detector

---

## 7. How to Run Everything

```bash
# Start the live bot (BOOM1000 paper trading)
python main.py

# Run the parameter optimizer and auto-apply results
python backtester.py BOOM1000 --apply

# Run optimizer and decide manually
python backtester.py BOOM1000

# Check current session metrics
cat logs/bot_metrics.json

# See all trades this session
cat logs/trade_log.csv
```

The Replit workflow is named **"Start application"** and runs `python main.py`.

---

## 8. Architecture for Android "Brain Update"

The Android app calls these Python scripts as its logic layer. When a "brain update" is released:
- The files that change are: `config.py` (always), and sometimes `strategy.py` or `trader.py`
- `config.py` is the single-file brain update for parameter changes
- `strategy.py` + `trader.py` changes are structural updates (new signals, new exit rules)

**Minimum update payload for a parameter-only brain update:** `config.py` alone.  
**Full strategy update payload:** `config.py` + `strategy.py` + `trader.py` + `ml_features.py`.

---

*End of handoff document. Update this file whenever a significant change is made.*
