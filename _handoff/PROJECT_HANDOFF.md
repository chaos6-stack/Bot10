# AI-Assisted Synth Index Spike Agent — Project Handoff
**Last updated:** 2026-06-03  
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
