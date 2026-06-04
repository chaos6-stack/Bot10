---
name: Backtester/Live Feature Alignment
description: Critical: backtester must use ml_features.extract_all_features() to match live strategy exactly; old inline _extract_features() caused optimizer to tune a ghost strategy
---

## The Problem
Before Change 010, `backtester.py` had its own inline feature extraction:
- `_calc_sma()`, `_calc_std()`, `_calc_rsi()`, `_calc_ema()`, `_ema_slope()`, `_extract_features()`

`strategy.py` (live) called `ml_features.extract_all_features()`.

These were different implementations — specifically `_ema_slope()` computed slope differently than `calculate_ema_gradient()`. This meant:
- Optimizer tuned RSI/squeeze/z-score params for backtester-EMA behavior
- Live bot ran with live-EMA behavior
- Best params from optimizer didn't actually apply to the live strategy

## The Fix
All backtester helper functions removed. `run_backtest()` now calls:
```python
feats = ml_features.extract_all_features(buf, window)
```

This is IDENTICAL to the live strategy call in `strategy.py`.

## Rule for Future Development
If you add a new feature calculation to `ml_features.py`, the backtester automatically picks it up via `extract_all_features()`. Do NOT add inline math to `backtester.py` — always add to `ml_features.py` and call it from there.

## Additional: Entry Logic Must Match
The backtester's entry decision logic must also mirror `strategy.py`. After Change 010 both use:
1. RECOVERY zone → skip
2. OVERDUE zone → enter unconditionally
3. Score threshold: `score = WEIGHT_CYCLE*cycle_p + WEIGHT_COMPRESSION*compress_p + WEIGHT_ENERGY*energy_p >= ENTRY_SCORE_THRESHOLD`

Any changes to strategy.py entry rules must be mirrored in backtester.py `run_backtest()`.
