---
name: Quantitative Audit Findings
description: audit.py results — ALL technical indicators have zero predictive power; only spike cycle timing has real edge on BOOM1000
---

## Summary
Run `python audit.py` to reproduce. Tested on 250,000 synthetic BOOM1000 ticks (5 seeds × 50,000).

## Feature-Spike Correlation (Section 1)
None of the technical indicators are statistically significant predictors of upcoming spikes:

| Feature | r_pb | p-value | Significant? |
|---|---|---|---|
| RSI | 0.0030 | 0.129 | NO |
| Z-score | 0.0011 | 0.586 | NO |
| Compression | 0.0034 | 0.093 | NO |
| Momentum | 0.0008 | 0.681 | NO |
| Down-ticks | -0.0010 | 0.635 | NO |
| Micro-std | -0.0012 | 0.549 | NO |

## Signal Permutation Tests (Section 2)
All entry signals fire at exactly the random baseline rate (~11.8%):

| Signal | Rate before spike | Baseline | p-value |
|---|---|---|---|
| Signal A (RSI+Squeeze) | 11.6% | 11.8% | 0.926 |
| Signal B (Squeeze+Z) | 11.8% | 11.8% | 0.384 |
| Signal D (Energy) | 11.6% | 11.8% | 0.712 |
| Random coin flip | 11.3% | 11.8% | 0.939 |

## RSI Deep Dive (Section 3)
- RSI < 28 fires on 40.3% of ALL ticks — not a selective signal at all
- The HIGHEST spike lift belongs to RSI 40-50 (1.23x) — the OPPOSITE of what the strategy targets
- RSI 0-10 (what the old strategy used) has lift of 0.95x — BELOW random baseline

**Why RSI is always near 0 on BOOM1000:** BOOM1000 drifts DOWN every tick (drift=-0.035). In a pure downtrend, avg_gain = 0, so RSI = 100 - 100/(1+0/al) = 0. RSI just reflects the drift, not spike proximity.

## Compression/Squeeze (Section 4)
- Pre-spike mean compression: 0.2500
- Non-spike mean compression: 0.2459
- Difference: +0.0041
- Welch t-test: p=0.169 → NOT significant

Squeeze does NOT precede spikes. Linear downtrend ALWAYS looks compressed relative to its 50-tick window.

## Expected Value (Section 5)
Random entry (15% of ticks): WR=13.5%, avg PnL = -0.73 pts/trade
Theoretical EV with SL=2.5, TP=20, Hold=120: -0.543 pts/trade
Strategy must generate >0.543 pts edge per trade just to break even.

## What DOES Work
Only the spike cycle counter has genuine mathematical grounding:
- Geometric distribution: P(spike on tick k | no spike yet) = 1-(1-1/1000)^k
- At tick 600: 45.1% cumulative probability
- At tick 1000: 63.2% cumulative probability
- This is math, not curve-fitting

## Overfitting Evidence
- Stage 1 score 64.34 → Stage 3 score 47.70 = -26% degradation
- Only 8-15 trades per combo in Stage 1 (1 lucky spike = +10 score points = noise)
- Fixed in Change 010: raised to 4,000 ticks/seed → 25-50 trades per combo
