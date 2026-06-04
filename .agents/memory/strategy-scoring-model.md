---
name: Strategy v3 Probability Scoring Model
description: Replaces elif cascade with weighted score; entry threshold 0.42; OVERDUE always triggers; RECOVERY always blocks
---

## The Problem with the Old Model
strategy.py used an if/elif cascade for 5 signals (A-E). Because Signal A (RSI oversold) fired nearly every tick on BOOM1000 (RSI≈0 always in a downtrend), Signals B-E were rarely evaluated. Signal E (OVERDUE zone — unconditional, the ONLY valid signal) was blocked by A.

## New Model (v3)
Three components evaluated simultaneously on every tick:

```python
cycle_p    = 1.0 - (1.0 - 1/SPIKE_CYCLE_LENGTH) ** ticks_since_spike
compress_p = max(0, (SQUEEZE_THRESHOLD - compression_ratio) / SQUEEZE_THRESHOLD)
energy_p   = min(down_ticks / 10.0, 1.0)   # BOOM; up_ticks for CRASH

score = WEIGHT_CYCLE * cycle_p + WEIGHT_COMPRESSION * compress_p + WEIGHT_ENERGY * energy_p
confidence = (WEIGHT_CYCLE * cycle_p) / score   # 1.0 = fully cycle-driven
```

## Config Params (config.py)
```python
ENTRY_SCORE_THRESHOLD = 0.42
WEIGHT_CYCLE          = 0.60   # proven
WEIGHT_COMPRESSION    = 0.20   # unproven audit p=0.169
WEIGHT_ENERGY         = 0.20   # unproven audit p=0.635
```

## Entry Rules
- RECOVERY zone: hard block (always HOLD)
- OVERDUE zone: hard trigger (always BUY/SELL)
- BUILDING/HOT: enter if score >= ENTRY_SCORE_THRESHOLD

## Score Behaviour at Key Cycle Points
- tick 150 (BUILDING start): cycle_p≈14% → base score≈0.08; needs strong unproven signals to pass 0.42
- tick 600 (HOT start): cycle_p≈45% → base score≈0.27; plus moderate signals → ~0.40 (borderline)
- tick 800: cycle_p≈55% → base score≈0.33; plus typical signals → ~0.47 (triggers)
- tick 1000+ (OVERDUE): hard trigger regardless of score

## Why Weights Are Fixed at 0.60 / 0.20 / 0.20
The audit (audit.py) showed that only the cycle component has proven statistical edge (geometric distribution of inter-spike intervals). Unproven components (compression, energy) are kept at 0.20 max so they can NEVER override cycle timing alone — they can only shift the threshold by ±0.20.

**Why:** If unproven signals had equal or dominant weight, entering at tick 150 (low cycle_p) would be driven by noise. The audit proved these signals fire at random baseline rate.
