---
name: Evaluator Score Calibration (v2)
description: Old formula had +50 base making all scores 45-55; removed base and recalibrated so 0=no edge, 45-65=good strategy
---

## The Problem
Old formula: `return max(0, min(100, 50.0 + raw))`

With typical BOOM1000 backtest stats (WR=13.5%, PF=0.8, NP=-50, DD=200):
raw ≈ 5.4 + 4.0 - 1.5 - 6.0 - 1.0 + 2.3 = +3.2
Final score = 53.2

ALL parameter combinations scored 45-55. The optimizer was differentiating noise (±5 points from 1-2 lucky spike captures).

## The Fix (v2)
Removed 50-point base. Recalibrated to actual achievable ranges on 8,000-tick runs:

```python
score_wr = min(wr / 0.30, 1.0) * 50.0          # 0-50 pts
score_pf = min(pf / 3.0, 1.0)  * 25.0          # 0-25 pts
score_np = max(min(np_ / 150.0, 1.0), -1.0) * 15.0   # ±15 pts
score_dd = -min(dd / 300.0, 1.0) * 15.0         # 0 to -15 pts
score_to = -to * 15.0                            # 0 to -15 pts
score_sc = sc * 10.0                             # 0-10 pts

raw = sum(above)   # NO base offset
return max(0, min(100, raw))
```

## Score Interpretation
- 0-10: worse than random entry
- 10-25: marginal, likely overfitting
- 25-45: reasonable, needs improvement
- 45-65: good — genuine edge
- 65+: excellent (rare without real market data)

## Example Scores
| Strategy | v1 score | v2 score |
|---|---|---|
| Random entry (WR=13.5%, PF=0.8) | ~50 | ~9 |
| Good cycle strategy (WR=20%, PF=1.5) | ~53 | ~48 |
| Perfect (WR=30%, PF=3.0) | ~58 | ~100 |

**Why:** The normalisation constants (÷0.30 for WR, ÷3.0 for PF, ÷150 for NP) are calibrated so that "genuinely good" values reach 100% of their component max. The ±15/±15 for NP/DD match realistic win/loss magnitudes on 8,000-tick runs with 1.0 lot.
