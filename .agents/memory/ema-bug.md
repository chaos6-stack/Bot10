---
name: EMA Gradient Bug (Fixed in Change 010)
description: calculate_ema_gradient() had dead else-branch making current EMA 1 tick stale; fixed with explicit slices
---

## The Bug
`ml_features.py`, function `calculate_ema_gradient()`, original code:
```python
for i in range(3, 0, -1):                       # i = 3, 2, 1
    subset = prices[:-i] if i > 0 else prices   # i > 0 ALWAYS TRUE
    ema_vals.append(calculate_ema(subset, window))
```

Since `i` is always > 0 in `range(3, 0, -1)`, the `else prices` branch was dead code. The three EMA calculations were:
- prices[:-3]  (3 ticks back)
- prices[:-2]  (2 ticks back)
- prices[:-1]  (1 tick back) ← wrongly called "current"

The "current" EMA was always 1 tick stale. `ema_slope` reported the slope from 3→1 ticks ago, not from 2 ticks ago → now.

## The Fix
```python
ema_two_ago = calculate_ema(prices[:-2], window)   # 2 ticks back
ema_current = calculate_ema(prices,      window)   # current tick (correct)
slope = (ema_current - ema_two_ago) / 2.0
```

## Impact
- Old Signal B gated on `slope >= -0.005` — was checking slope from 3→1 ticks ago
- Old Signal C gated on `slope > 0` — same problem
- In the new v3 scoring model, ema_slope is NOT directly used for entry decisions, so this bug no longer affects trade logic — but the correct slope is available in analytics if needed later.

## How to Verify Fix
Print `features["ema_slope"]` on consecutive ticks. Before fix: slope would lag price direction changes by 1 tick. After fix: slope responds immediately to current tick.
