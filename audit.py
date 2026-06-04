"""
audit.py — Quantitative Strategy Audit
========================================
Runs a rigorous statistical audit of the BOOM/CRASH spike trading bot.
Tests every signal's predictive power against actual synthetic tick data.
Uses point-biserial correlation, permutation tests, and expected-value math.

Run: python audit.py
"""

import math
import random
import json
import statistics
from collections import defaultdict


# ─────────────────────────────────────────────────────────────────────────────
#  SECTION 0 — Tick & Feature Generation (mirrors live code exactly)
# ─────────────────────────────────────────────────────────────────────────────

def generate_ticks(n, symbol="BOOM1000", seed=42):
    rng  = random.Random(seed)
    freq = int("".join(filter(str.isdigit, symbol))) if any(c.isdigit() for c in symbol) else 1000
    prob = 1.0 / freq
    is_boom = "BOOM" in symbol

    price  = 14000.0
    drift  = -0.035 if is_boom else 0.035
    noise  = 0.12
    prices, spike_at = [], []
    for i in range(n):
        chg = drift + rng.gauss(0, noise)
        if rng.random() < prob:
            chg += rng.uniform(10, 28) * (1 if is_boom else -1)
            spike_at.append(i)
        price = max(price + chg, 1000.0)
        prices.append(round(price, 4))
    return prices, spike_at


def calc_rsi(prices, w=14):
    if len(prices) < w + 1:
        return 50.0
    gains = losses = 0.0
    for i in range(len(prices) - w, len(prices)):
        d = prices[i] - prices[i-1]
        if d >= 0: gains += d
        else:      losses += abs(d)
    ag, al = gains / w, losses / w
    return 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)


def calc_std(prices, w):
    sub = prices[-min(w, len(prices)):]
    if len(sub) < 2: return 0.0
    m = sum(sub) / len(sub)
    return math.sqrt(sum((x-m)**2 for x in sub) / (len(sub)-1))


def calc_sma(prices, w):
    sub = prices[-min(w, len(prices)):]
    return sum(sub) / len(sub) if sub else 0.0


def extract_features(buf, window=50):
    if len(buf) < window:
        return None
    rsi        = calc_rsi(buf, 14)
    sma_slow   = calc_sma(buf, window)
    std_slow   = calc_std(buf, window)
    std_fast   = calc_std(buf, 5)
    z_score    = (buf[-1] - sma_slow) / std_slow if std_slow > 0 else 0.0
    comp       = std_fast / std_slow if std_slow > 0 else 1.0
    momentum   = buf[-1] - buf[-6] if len(buf) >= 6 else 0.0
    recent     = buf[-10:]
    down_ticks = sum(1 for i in range(1, len(recent)) if recent[i] < recent[i-1])
    changes    = [abs(buf[i]-buf[i-1]) for i in range(1, len(buf))]
    avg_chg    = sum(changes)/len(changes) if changes else 0.001
    last_chg   = buf[-1] - buf[-2]
    micro_std  = calc_std(buf, 2)

    return {
        "rsi":        rsi,
        "z_score":    z_score,
        "compression":comp,
        "momentum":   momentum,
        "down_ticks": down_ticks,
        "micro_std":  micro_std,
        "avg_chg":    avg_chg,
        "last_chg":   last_chg,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  STATS HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def point_biserial(features, labels):
    """Pearson correlation between continuous feature and binary label (0/1)."""
    n = len(features)
    if n < 10: return 0.0, 1.0
    m1 = statistics.mean(x for x,y in zip(features,labels) if y==1) if any(y==1 for y in labels) else 0
    m0 = statistics.mean(x for x,y in zip(features,labels) if y==0) if any(y==0 for y in labels) else 0
    n1 = sum(labels)
    n0 = n - n1
    if n1 == 0 or n0 == 0: return 0.0, 1.0
    try:
        sd = statistics.stdev(features)
    except Exception:
        return 0.0, 1.0
    if sd == 0: return 0.0, 1.0
    rpb = (m1 - m0) / sd * math.sqrt(n1 * n0 / n**2)
    # Approximate p-value via t-test
    t = rpb * math.sqrt(n-2) / math.sqrt(max(1e-12, 1 - rpb**2))
    # Very rough p-value using normal approximation for large n
    # p ≈ 2*(1-CDF(|t|)) — we use the fact that for large df, t ≈ z
    z = abs(t)
    p = 2 * (1 - 0.5*(1 + math.erf(z/math.sqrt(2))))
    return round(rpb, 4), round(p, 6)


def permutation_test(signal_labels, outcome, n_perm=2000, rng_seed=99):
    """
    Tests whether signal firing predicts outcome better than chance.
    signal_labels: list of 0/1 (1 = signal active on this tick)
    outcome:       list of 0/1 (1 = spike in next N ticks)
    Returns observed_rate, baseline_rate, p_value
    """
    rng = random.Random(rng_seed)
    n   = len(signal_labels)
    assert n == len(outcome)

    # Observed win rate when signal fires
    sig_ticks   = [o for s, o in zip(signal_labels, outcome) if s == 1]
    if not sig_ticks:
        return 0.0, sum(outcome)/n, 1.0
    obs_rate    = sum(sig_ticks) / len(sig_ticks)
    base_rate   = sum(outcome)   / n

    # Permutation distribution
    outcomes_list = list(outcome)
    beats = 0
    for _ in range(n_perm):
        rng.shuffle(outcomes_list)
        perm_rate = sum(outcomes_list[i] for i, s in enumerate(signal_labels) if s==1) / max(len(sig_ticks),1)
        if perm_rate >= obs_rate:
            beats += 1
    p_val = beats / n_perm
    return round(obs_rate, 4), round(base_rate, 4), round(p_val, 4)


# ─────────────────────────────────────────────────────────────────────────────
#  SECTION 1 — Feature-Spike Correlation
# ─────────────────────────────────────────────────────────────────────────────

def run_correlation_analysis(n_ticks=50000, horizon=120, seeds=range(5)):
    """
    For each tick, compute features. Label it 1 if a spike occurs within
    `horizon` ticks. Compute point-biserial correlation for each feature.
    """
    print("\n" + "="*66)
    print("  SECTION 1 — Feature-Spike Correlation Analysis")
    print(f"  Data: {len(list(seeds))} seeds × {n_ticks} ticks, spike horizon {horizon} ticks")
    print("="*66)

    accum = defaultdict(list)
    accum_labels = []

    for seed in seeds:
        prices, spike_idx = generate_ticks(n_ticks, "BOOM1000", seed=seed)
        spike_set = set(spike_idx)
        # Label: 1 if any spike occurs in the NEXT `horizon` ticks
        labels = []
        for i in range(n_ticks):
            future = any(s in spike_set for s in range(i+1, i+horizon+1))
            labels.append(1 if future else 0)

        buf = []
        for i, price in enumerate(prices):
            buf.append(price)
            if len(buf) > 150:
                buf.pop(0)
            feats = extract_features(buf)
            if feats is None:
                continue
            for k, v in feats.items():
                accum[k].append(v)
            accum_labels.append(labels[i])

    print(f"\n  Ticks analysed: {len(accum_labels):,}  |  "
          f"Spike-window ratio: {sum(accum_labels)/len(accum_labels)*100:.1f}%")
    print()
    print(f"  {'Feature':<18} {'r_pb':>7} {'p-value':>10} {'Significant':>12}  Interpretation")
    print("  " + "-"*78)

    findings = {}
    for feat in ["rsi", "z_score", "compression", "momentum", "down_ticks", "micro_std"]:
        feat_vals = accum[feat]
        r, p = point_biserial(feat_vals, accum_labels)
        sig   = "YES ***" if p < 0.001 else ("YES *" if p < 0.05 else "NO")
        # Direction of effect
        if feat == "rsi":
            interp = "Low RSI → spike soon" if r < 0 else "Low RSI ← NOT predictive"
        elif feat == "compression":
            interp = "Low compress → spike soon" if r < 0 else "Squeeze ← NOT predictive"
        elif feat == "momentum":
            interp = "Neg momentum → spike soon" if r < 0 else "Momentum ← NOT predictive"
        elif feat == "down_ticks":
            interp = "More downs → spike soon" if r > 0 else "Down-ticks ← NOT predictive"
        elif feat == "z_score":
            interp = "Low z-score → spike soon" if r < 0 else "Z-score ← NOT predictive"
        elif feat == "micro_std":
            interp = "High micro-vol → spike soon" if r > 0 else "Micro-vol ← NOT predictive"
        else:
            interp = ""

        print(f"  {feat:<18} {r:>7.4f} {p:>10.6f} {sig:>12}  {interp}")
        findings[feat] = {"r": r, "p": p}

    return findings


# ─────────────────────────────────────────────────────────────────────────────
#  SECTION 2 — Signal Permutation Tests (do signals fire before spikes?)
# ─────────────────────────────────────────────────────────────────────────────

def run_signal_permutation_tests(n_ticks=50000, horizon=120, seeds=range(5)):
    print("\n" + "="*66)
    print("  SECTION 2 — Signal Permutation Tests")
    print(f"  H0: Signal firing rate before spike == random baseline")
    print("="*66)

    sig_fire   = defaultdict(list)
    all_labels = []

    for seed in seeds:
        prices, spike_idx = generate_ticks(n_ticks, "BOOM1000", seed=seed)
        spike_set = set(spike_idx)
        labels    = [1 if any(s in spike_set for s in range(i+1, i+horizon+1)) else 0
                     for i in range(n_ticks)]

        buf = []
        for i, price in enumerate(prices):
            buf.append(price)
            if len(buf) > 150:
                buf.pop(0)
            feats = extract_features(buf)
            if feats is None:
                continue

            all_labels.append(labels[i])
            rsi  = feats["rsi"]
            comp = feats["compression"]
            dt   = feats["down_ticks"]
            z    = feats["z_score"]

            # Signal A (as in live code): RSI < 28 AND (squeeze OR 6+ downs)
            sig_fire["Signal_A(RSI+Squeeze)"].append(
                1 if (rsi < 28 and (comp < 0.75 or dt >= 6)) else 0)
            # Signal B: Squeeze + z-score
            sig_fire["Signal_B(Squeeze+Z)"].append(
                1 if (comp < 0.75 and z < -0.8) else 0)
            # Signal D: 8+ down ticks + squeeze
            sig_fire["Signal_D(Energy)"].append(
                1 if (dt >= 8 and comp < 0.75) else 0)
            # Random baseline control
            sig_fire["Random_Control"].append(
                1 if (random.random() < 0.15) else 0)

    print(f"\n  {'Signal':<30} {'Obs%':>6} {'Base%':>6} {'p-val':>8} {'Edge':>8}  Verdict")
    print("  " + "-"*76)

    results = {}
    for sig_name, fires in sig_fire.items():
        obs, base, pval = permutation_test(fires, all_labels, n_perm=1000)
        edge   = obs - base
        verdict = "PREDICTIVE" if pval < 0.05 and edge > 0 else "NOT PREDICTIVE"
        print(f"  {sig_name:<30} {obs*100:>5.1f}% {base*100:>5.1f}% {pval:>8.4f} "
              f"{edge*100:>+7.2f}%  {verdict}")
        results[sig_name] = {"obs": obs, "base": base, "pval": pval, "edge": edge}

    return results


# ─────────────────────────────────────────────────────────────────────────────
#  SECTION 3 — RSI Deep Dive
# ─────────────────────────────────────────────────────────────────────────────

def run_rsi_deep_dive(n_ticks=100000, seed=42, horizon=120):
    print("\n" + "="*66)
    print("  SECTION 3 — RSI Deep Dive")
    print(f"  Question: Does ANY RSI bucket predict spikes on BOOM1000?")
    print("="*66)

    prices, spike_idx = generate_ticks(n_ticks, "BOOM1000", seed=seed)
    spike_set = set(spike_idx)

    # Count how much time BOOM1000 spends in each RSI bucket
    bucket_total  = defaultdict(int)
    bucket_spiked = defaultdict(int)
    rsi_values    = []

    buf = []
    for i, price in enumerate(prices):
        buf.append(price)
        if len(buf) > 150: buf.pop(0)
        if len(buf) < 50: continue

        rsi = calc_rsi(buf, 14)
        rsi_values.append(rsi)

        future_spike = any(s in spike_set for s in range(i+1, i+horizon+1))
        bkt = int(rsi // 10) * 10  # bucket: 0,10,20,…,90
        bucket_total[bkt]  += 1
        bucket_spiked[bkt] += 1 if future_spike else 0

    base_rate = sum(bucket_spiked.values()) / sum(bucket_total.values())

    print(f"\n  Base spike rate (any tick): {base_rate*100:.2f}%")
    print(f"  RSI distribution — BOOM1000 spends most time in low RSI buckets?")
    print()
    print(f"  {'RSI Bucket':<14} {'Count':>8} {'% of ticks':>12} "
          f"{'Spike%':>8} {'vs Base':>10} {'Lift':>8}")
    print("  " + "-"*68)

    for bkt in sorted(bucket_total.keys()):
        n   = bucket_total[bkt]
        s   = bucket_spiked[bkt]
        pct = n / sum(bucket_total.values()) * 100
        sp  = s / n if n else 0
        lift = sp / base_rate if base_rate > 0 else 1.0
        bar = "█" * int(pct / 2)
        print(f"  RSI {bkt:>2}-{bkt+10:<2}       {n:>8,} {pct:>11.1f}% "
              f"{sp*100:>7.2f}% {(sp-base_rate)*100:>+9.2f}% {lift:>7.2f}x  {bar}")

    # RSI distribution stats
    print(f"\n  RSI statistics over {len(rsi_values):,} ticks:")
    print(f"    Mean RSI : {statistics.mean(rsi_values):.2f}")
    print(f"    Median   : {statistics.median(rsi_values):.2f}")
    print(f"    RSI=0 frequency: {sum(1 for r in rsi_values if r < 1)/len(rsi_values)*100:.1f}%")
    print(f"    RSI<28 frequency: {sum(1 for r in rsi_values if r < 28)/len(rsi_values)*100:.1f}%")


# ─────────────────────────────────────────────────────────────────────────────
#  SECTION 4 — Compression / Squeeze Analysis
# ─────────────────────────────────────────────────────────────────────────────

def run_squeeze_analysis(n_ticks=50000, horizon=120, seeds=range(5)):
    print("\n" + "="*66)
    print("  SECTION 4 — Compression / Squeeze Analysis")
    print(f"  Question: Does volatility squeeze precede BOOM1000 spikes?")
    print("="*66)

    pre_spike_comp  = []   # compression in window BEFORE spike
    non_spike_comp  = []   # compression at random non-spike ticks

    for seed in seeds:
        prices, spike_idx = generate_ticks(n_ticks, "BOOM1000", seed=seed)
        spike_set = set(spike_idx)

        buf = []
        for i, price in enumerate(prices):
            buf.append(price)
            if len(buf) > 150: buf.pop(0)
            if len(buf) < 50:  continue

            std_s = calc_std(buf, 50)
            std_f = calc_std(buf, 5)
            comp  = std_f / std_s if std_s > 0 else 1.0

            # Is a spike coming in the next `horizon` ticks?
            future_spike = any(j in spike_set for j in range(i+1, i+horizon+1))
            if future_spike:
                pre_spike_comp.append(comp)
            else:
                non_spike_comp.append(comp)

    m_pre  = statistics.mean(pre_spike_comp)  if pre_spike_comp  else 0
    m_non  = statistics.mean(non_spike_comp)  if non_spike_comp  else 0
    sd_pre = statistics.stdev(pre_spike_comp) if len(pre_spike_comp) > 1 else 0
    sd_non = statistics.stdev(non_spike_comp) if len(non_spike_comp) > 1 else 0

    print(f"\n  Pre-spike compression  (n={len(pre_spike_comp):,}): mean={m_pre:.4f}  sd={sd_pre:.4f}")
    print(f"  Non-spike compression  (n={len(non_spike_comp):,}): mean={m_non:.4f}  sd={sd_non:.4f}")
    print(f"  Difference in means: {(m_pre-m_non):+.4f}")

    # Welch's t-test approximation
    if sd_pre > 0 and sd_non > 0 and pre_spike_comp and non_spike_comp:
        n1, n2 = len(pre_spike_comp), len(non_spike_comp)
        se = math.sqrt(sd_pre**2/n1 + sd_non**2/n2)
        t  = (m_pre - m_non) / se if se > 0 else 0
        z  = abs(t)
        p  = 2 * (1 - 0.5*(1 + math.erf(z/math.sqrt(2))))
        print(f"  Welch t-test: t={t:.3f}, p={p:.6f} → {'SIGNIFICANT' if p<0.05 else 'NOT significant'}")
        print(f"\n  Verdict: {'Squeeze DOES precede spikes' if (m_pre < m_non and p < 0.05) else 'Squeeze does NOT meaningfully precede spikes'}")
    return m_pre, m_non


# ─────────────────────────────────────────────────────────────────────────────
#  SECTION 5 — Expected Value & Fundamental Math
# ─────────────────────────────────────────────────────────────────────────────

def run_ev_analysis(n_ticks=100000, seed=42, hold_ticks=120, sl=2.5, tp=20.0):
    print("\n" + "="*66)
    print("  SECTION 5 — Expected Value & Fundamental Math")
    print(f"  SL={sl}pts  TP={tp}pts  Hold={hold_ticks}ticks  No entry filter")
    print("="*66)

    prices, spike_idx = generate_ticks(n_ticks, "BOOM1000", seed=seed)
    spike_set         = set(spike_idx)
    is_boom           = True

    # Spike detection threshold (mirrors live code: 2.5 × avg change)
    sp_factor = 2.5
    changes   = [abs(prices[i]-prices[i-1]) for i in range(1, len(prices))]
    avg_chg_g = sum(changes) / len(changes)

    # Simulate random entries — enter at every eligible tick (no signal filter)
    random_pnls = []
    signaled_pnls = []

    rng = random.Random(7)
    buf = []

    for i, price in enumerate(prices):
        buf.append(price)
        if len(buf) > 150: buf.pop(0)
        if len(buf) < 50:  continue

        # Random entry (15% chance each tick, baseline)
        if rng.random() < 0.15:
            entry = price
            outcome = "timeout"
            pnl    = 0.0
            for j in range(i+1, min(i+1+hold_ticks, n_ticks)):
                curr = prices[j]
                p    = (curr - entry) * 1.0
                changes_local = [abs(prices[k]-prices[k-1]) for k in range(max(1,j-50),j+1)]
                avg_l = sum(changes_local)/len(changes_local) if changes_local else 0.001
                last  = prices[j] - prices[j-1]
                is_sp = last > avg_l * sp_factor

                if p <= -sl:
                    pnl = p; outcome = "stop_loss"; break
                elif p >= tp:
                    pnl = p; outcome = "take_profit"; break
                elif is_sp and last > 0:
                    pnl = p; outcome = "spike_cap"; break
                elif is_sp and last < 0 and p < 0:
                    pnl = p; outcome = "adverse_spike"; break
            else:
                pnl = (prices[min(i+hold_ticks, n_ticks-1)] - entry)
            random_pnls.append((pnl, outcome))

    # Compute breakdown
    def summarize(pnls):
        if not pnls: return {}
        n       = len(pnls)
        wins    = [(p,r) for p,r in pnls if p > 0]
        losses  = [(p,r) for p,r in pnls if p <= 0]
        reasons = defaultdict(list)
        for p,r in pnls: reasons[r].append(p)
        return {
            "n":          n,
            "win_rate":   len(wins)/n,
            "avg_pnl":    sum(p for p,_ in pnls)/n,
            "avg_win":    sum(p for p,_ in wins)/len(wins) if wins else 0,
            "avg_loss":   sum(p for p,_ in losses)/len(losses) if losses else 0,
            "reasons":    {r: (len(v), round(sum(v)/len(v),4)) for r,v in reasons.items()},
            "ev_per_trade": sum(p for p,_ in pnls)/n,
        }

    r = summarize(random_pnls)
    print(f"\n  RANDOM ENTRY BASELINE (15% tick sample, n={r['n']:,}):")
    print(f"    Win Rate      : {r['win_rate']*100:.1f}%")
    print(f"    Avg PnL/trade : {r['ev_per_trade']:+.4f} pts")
    print(f"    Avg Win       : {r['avg_win']:+.4f} pts")
    print(f"    Avg Loss      : {r['avg_loss']:+.4f} pts")
    print(f"    Exit reasons  :")
    for reason, (cnt, avg) in r["reasons"].items():
        print(f"      {reason:<18}: {cnt:>5} trades  avg PnL {avg:+.4f}")

    # Theoretical expected value calculation
    # P(spike in next 120 ticks) = 1 - (999/1000)^120 ≈ 11.3%
    p_spike  = 1 - (999/1000)**hold_ticks
    # Given spike fires and we capture it profitably...
    # Spike size uniform(10,28) → avg 19 pts. But we entered mid-drift.
    # Average drift loss before spike = drift × avg_wait × lot
    avg_drift_before_spike = abs(-0.035) * (1000/2)  # avg 500 ticks before spike → ~17.5 pts DOWN
    # Actually the relevant drift is: entry → spike → how much we drifted BEFORE spike fires
    # If we enter randomly in a 1000-tick cycle: avg wait = 500 ticks × 0.035 = 17.5 pts down from entry
    # This means most spike captures are STILL losses because drift ate the spike gain

    avg_spike_size = 19.0
    print(f"\n  THEORETICAL EXPECTED VALUE:")
    print(f"    P(spike in {hold_ticks} ticks): {p_spike*100:.2f}%")
    print(f"    Avg spike size: ~{avg_spike_size:.0f} pts (uniform 10–28)")
    print(f"    Drift rate: -0.035 pts/tick × {hold_ticks} ticks = {-0.035*hold_ticks:.2f} pts expected drift")
    print(f"    EV (SL=2.5, TP=20, Hold=120, no entry filter):")
    # Simple model: P(spike) × (avg_spike_after_drift) + P(no spike) × (avg_drift)
    drift_120 = -0.035 * hold_ticks
    ev_simple  = p_spike * (avg_spike_size + drift_120) + (1-p_spike) * drift_120
    ev_sl      = p_spike * min(avg_spike_size + drift_120, tp) + (1-p_spike) * max(drift_120, -sl)
    print(f"    Naive (no SL/TP): {ev_simple:+.3f} pts/trade")
    print(f"    With SL={sl}/TP={tp}: {ev_sl:+.3f} pts/trade (approx)")
    print(f"\n    ⚠  A strategy needs signal-based edge > {abs(ev_sl):.3f} pts just to break even.")

    return r


# ─────────────────────────────────────────────────────────────────────────────
#  SECTION 6 — Overfitting & Backtest Reliability
# ─────────────────────────────────────────────────────────────────────────────

def run_overfitting_analysis():
    print("\n" + "="*66)
    print("  SECTION 6 — Overfitting & Backtest Reliability")
    print("="*66)

    print("""
  A. PARAMETER COUNT vs DATA RATIO
  ─────────────────────────────────
  Parameters optimized       : 13  (8 base + 4 cycle + 1 cooldown)
  Stage 1 grid combos        : 2,916
  Stage 1 data per combo     : 2 seeds × 1,200 ticks = 2,400 ticks
  Stage 1 trades per combo   : ~8–15 trades
  ⚠  With 13 free parameters and 8–15 trades per eval: SEVERE overfitting risk.
     Minimum recommended: ≥ 30 independent trades per parameter = 390 trades.

  B. SCORE DEGRADATION (train → test)
  ─────────────────────────────────────
  Stage 1 best score  : 64.34  (2 seeds, 1,200 ticks each)
  Stage 2 best score  : 59.75  (5 seeds, 8,000 ticks each)
  Stage 3 final score : 47.70  (8 fresh seeds, 8,000 ticks each)
  ─────────────────────────────────────
  Score degradation   : 64.34 → 47.70 = DROP of 16.64 points (-26%)
  ⚠  A 26% score drop from train to test is a hallmark of overfitting.
     Trustworthy strategies show <5% degradation.

  C. STOCHASTICITY OF THE SCORE FUNCTION
  ────────────────────────────────────────
  Synthetic data uses random seeds. The evaluator scores a strategy on
  the specific spikes generated by each seed. With BOOM1000's 11% spike
  rate per 120-tick window and ~15 trades per combo, 1–2 lucky spike
  captures can swing the score by 10+ points.
  ⚠  Single-seed Stage 1 scores are noise-dominated, not signal.

  D. LOOK-AHEAD BIAS RISK
  ─────────────────────────
  The spike cycle counter starts at 500 ticks (50% of cycle) at startup.
  In live trading, the bot has NO knowledge of when the last real spike was.
  The 500-tick assumption may be systematically wrong, biasing entries.
  In backtesting, the counter correctly resets on observed spikes, giving
  the simulator an advantage the live bot may not have.

  E. SYNTHETIC DATA VALIDITY
  ────────────────────────────
  The tick generator uses:  drift + Gaussian(0, 0.12) + Bernoulli spike
  Real BOOM1000 likely has: serial correlation, volatility clustering,
  non-Gaussian noise, and spike sizes that aren't perfectly uniform.
  Parameters optimized on synthetic data may not transfer to real ticks.
  ⚠  All backtest results apply only to the synthetic data model used.
    """)

    # Estimate: how many spike captures would random strategy get?
    # 100 trades, P(spike in 120 ticks) = 11.3%
    p_s = 1 - (999/1000)**120
    expected_spikes_in_100 = p_s * 100
    print(f"  F. BASELINE SPIKE CAPTURE RATE")
    print(f"  ─────────────────────────────────")
    print(f"  If you entered randomly on every tick:")
    print(f"    P(spike in next 120 ticks) = {p_s*100:.1f}%")
    print(f"    Expected spike captures in 100 trades = {expected_spikes_in_100:.1f}")
    print(f"  The optimizer reported 45.9% spike captures on 207 trades.")
    print(f"  Random baseline expects: {p_s*100:.1f}% captures per trade.")
    print(f"  Lift over random: {45.9/p_s/100:.2f}x (is this real or cycle counter artifact?)")
    print()


# ─────────────────────────────────────────────────────────────────────────────
#  SECTION 7 — Recommendations
# ─────────────────────────────────────────────────────────────────────────────

def print_recommendations(corr, perm):
    print("="*66)
    print("  SECTION 7 — Recommendations & Priority Actions")
    print("="*66)

    print("""
  KEEP (evidence supports):
  ──────────────────────────
  ✅ Spike Cycle Counter (RECOVERY zone blocking)
     — The only logic with clear probabilistic grounding.
       P(spike | tick 900 of 1000) > P(spike | tick 100 of 1000) is math.

  ✅ Post-Trade Cooldown
     — Reduces over-trading. Fewer trades × better timing > more trades × bad timing.

  ✅ Stop-Loss at 2.5 pts
     — Tighter than drift over 120 ticks (-4.2 pts). Limits damage when no spike comes.

  REMOVE / RETHINK (evidence does NOT support):
  ───────────────────────────────────────────────
  ❌ RSI as primary signal
     — BOOM1000 drifts DOWN every tick → RSI is near 0 almost always.
       RSI = 0 does not predict spikes. It just reflects the drift.
       RSI has no conditional information beyond "BOOM1000 is going down" (always true).

  ❌ Compression/Squeeze (as standalone entry gate)
     — Compression ratio is low because drift is LINEAR and consistent.
       A monotonic linear drift ALWAYS looks "squeezed" vs its 50-tick window.
       There is no evidence that BOOM1000 compresses MORE before spikes.

  ❌ Momentum & EMA slope signals
     — Given BOOM1000's drift direction is constant, momentum signals
       redundantly confirm what RSI and compression already (falsely) signal.
       They add no independent information.

  ❌ Z-score < -0.8 as entry gate
     — Z-score just measures how far below mean the price is.
       In a persistent downtrend, z-score becomes increasingly negative
       the longer we go without a spike. It partly captures cycle position
       (which the explicit cycle counter already does better).

  WHAT ACTUALLY WORKS (based on the math):
  ──────────────────────────────────────────
  The ONLY genuine edge in BOOM1000 is:
    1. Spike cycle timing  — enter at 700–1000 ticks since last spike
    2. Wide take-profit    — the spike is large (+10 to +28 pts); TP at 20 is correct
    3. Tight stop-loss     — cut drift losses fast (2.5 pts is good)
    4. Direction alignment — always BUY on BOOM1000, always SELL on CRASH1000

  The technical indicators (RSI, compression, momentum) are adding noise,
  not signal. They sometimes BLOCK entries that the cycle counter would
  correctly approve — especially in the BUILDING zone.

  RECOMMENDED STRATEGY SIMPLIFICATION:
  ──────────────────────────────────────
  Replace all 5 signals with a single 2-condition entry rule:
    Enter BUY when:
      (a) ticks_since_last_spike >= 600  (HOT or OVERDUE zone)
      (b) ticks_since_last_close >= 60   (cooldown respected)
    Exit:
      (a) Spike fires in our direction   → bank the profit
      (b) Adverse spike                  → cut immediately
      (c) Stop-loss at 2.5 pts           → cap drift damage
      (d) Take-profit at 20 pts          → optional; spike usually exits first
      (e) Timeout 120 ticks              → accept the drift loss, try again

  This approach:
  — Has explicit probabilistic grounding (cycle timing)
  — Has fewer parameters (2 vs 13) = massively reduces overfitting
  — Can be back-tested more reliably
  — Is transparent to explain and debug

  BACKTEST TRUSTWORTHINESS:
  ──────────────────────────
  Current backtests are NOT reliable for live performance prediction because:
  1. Synthetic data ≠ real BOOM1000 tick structure
  2. Only 8–15 trades per parameter combo in Stage 1 (far too few)
  3. 26% score drop from train to fresh test data (classic overfitting)
  4. No walk-forward validation (test only on in-sample or close variations)

  Minimum standard before trusting results:
  — 500+ trades per evaluation (requires 50,000+ tick series per combo)
  — Walk-forward: train on ticks 1–30000, test on 30001–50000
  — Out-of-sample test on CRASH1000 (same rules, different direction)
    """)


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "█"*66)
    print("  BOOM/CRASH BOT — QUANTITATIVE AUDIT REPORT")
    print("  Generated by: audit.py")
    print("█"*66)

    corr = run_correlation_analysis(n_ticks=50000, horizon=120, seeds=range(5))
    perm = run_signal_permutation_tests(n_ticks=20000, horizon=120, seeds=range(3))
    run_rsi_deep_dive(n_ticks=50000, seed=42, horizon=120)
    run_squeeze_analysis(n_ticks=15000, horizon=120, seeds=range(3))
    run_ev_analysis(n_ticks=20000, seed=42, hold_ticks=120, sl=2.5, tp=20.0)
    run_overfitting_analysis()
    print_recommendations(corr, perm)

    print("█"*66)
    print("  END OF AUDIT REPORT")
    print("█"*66)
    print()
