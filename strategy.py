# strategy.py
"""
Spike Trading Strategy Engine (Boom/Crash Specifics)
v3 — Probability Scoring Model (replaces elif signal cascade)

Entry logic is now driven by a weighted composite score (0.0–1.0):
  - Cycle timing      60% weight  (only proven predictor — geometric distribution)
  - Compression       20% weight  (unproven; audit r_pb=0.003, kept at low weight)
  - Directional energy 20% weight (unproven; audit r_pb=-0.001, kept at low weight)

Entry fires when score >= ENTRY_SCORE_THRESHOLD (default 0.42), except:
  - RECOVERY zone: hard block (always HOLD)
  - OVERDUE zone:  hard trigger (always BUY/SELL regardless of score)
"""

import ml_features
import config


class SpikeStrategy:
    def __init__(self, symbol: str = config.ACTIVE_SYMBOL):
        self.symbol = symbol.upper()
        self.is_boom  = "BOOM"  in self.symbol
        self.is_crash = "CRASH" in self.symbol
        self.spike_threshold_factor = config.SPIKE_THRESHOLD_FACTOR

        # ── Spike Cycle Counter ──────────────────────────────────────────────
        # Start at 50% of cycle — puts us in BUILDING zone immediately.
        # We genuinely don't know when the last spike was at startup.
        self.ticks_since_last_spike: int = config.SPIKE_CYCLE_LENGTH // 2
        self.total_spikes_observed: int  = 0

    # ─────────────────────────────────────────────────────────────────────────
    #  CYCLE STATE
    # ─────────────────────────────────────────────────────────────────────────

    def _compute_cycle_state(self) -> tuple[float, str]:
        """
        Returns (multiplier, zone_label) based on elapsed ticks since last spike.

        multiplier < 1.0  → suppressed / RECOVERY
        multiplier = 1.0  → neutral (BUILDING)
        multiplier > 1.0  → elevated: relax thresholds, scale lots (HOT / OVERDUE)

        Zones:  RECOVERY | BUILDING | HOT | OVERDUE
        """
        cycle_pos = self.ticks_since_last_spike / config.SPIKE_CYCLE_LENGTH
        early     = config.CYCLE_EARLY_ZONE
        hot       = config.CYCLE_HOT_ZONE

        if cycle_pos < early:
            progress   = cycle_pos / early
            multiplier = 0.1 + progress * 0.4          # 0.10 → 0.50
            zone       = "RECOVERY"

        elif cycle_pos < hot:
            progress   = (cycle_pos - early) / (hot - early)
            multiplier = 0.5 + progress * 0.5           # 0.50 → 1.00
            zone       = "BUILDING"

        elif cycle_pos < 1.0:
            progress   = (cycle_pos - hot) / (1.0 - hot)
            multiplier = 1.0 + progress * 0.75          # 1.00 → 1.75
            zone       = "HOT"

        else:
            overage    = min((cycle_pos - 1.0) / 0.5, 1.0)
            multiplier = 1.75 + overage * 0.25          # 1.75 → 2.00
            zone       = "OVERDUE"

        return round(multiplier, 3), zone

    # ─────────────────────────────────────────────────────────────────────────
    #  PROBABILITY SCORING MODEL
    # ─────────────────────────────────────────────────────────────────────────

    def _compute_spike_probability(
        self,
        features:   dict,
        down_ticks: int,
        up_ticks:   int,
    ) -> tuple[float, float, dict]:
        """
        Computes a weighted composite spike probability score (0.0–1.0).

        Replaces the old if/elif signal cascade with a continuous score that
        evaluates ALL components simultaneously — no hidden elif ordering.

        Component weights (evidence-based from quantitative audit):
          WEIGHT_CYCLE       = 0.60  — ONLY proven predictor (geometric distribution)
          WEIGHT_COMPRESSION = 0.20  — unproven; kept small so it can't override cycle
          WEIGHT_ENERGY      = 0.20  — unproven; kept small so it can't override cycle

        Returns:
          score      : composite probability (0.0–1.0)
          confidence : fraction of score driven by the proven cycle component (0.0–1.0)
          breakdown  : dict of per-component values for logging / diagnostics
        """

        # ── Component 1: Cycle timing (geometric probability model) ──────────
        # Based on the geometric distribution of inter-spike intervals.
        # P(spike on tick k | survived k ticks without spike)
        # = 1 - (1 - 1/N)^k  where N = SPIKE_CYCLE_LENGTH
        #
        # This is the ONLY component with proven statistical grounding.
        # Rises from ~0% at tick 0 to ~63% at tick N, continues rising beyond.
        k       = self.ticks_since_last_spike
        cycle_p = 1.0 - (1.0 - 1.0 / config.SPIKE_CYCLE_LENGTH) ** k
        cycle_p = min(cycle_p, 1.0)

        # ── Component 2: Volatility compression ──────────────────────────────
        # Audit result: Welch t-test p=0.169 (not significant).
        # Included at low weight — if squeeze genuinely precedes spikes on real
        # data, the small weight captures it without overpowering cycle timing.
        comp       = features.get("compression_ratio", 1.0)
        sq_thresh  = config.SQUEEZE_THRESHOLD
        compress_p = max(0.0, (sq_thresh - comp) / sq_thresh)

        # ── Component 3: Directional energy ──────────────────────────────────
        # Count of down-ticks (BOOM) or up-ticks (CRASH) in last 10 ticks.
        # Audit result: r_pb = -0.001 (not significant).
        # Included at low weight as a proxy for short-term momentum buildup.
        if self.is_boom:
            energy_p = min(down_ticks / 10.0, 1.0)
        else:
            energy_p = min(up_ticks / 10.0, 1.0)

        # ── Weighted composite ────────────────────────────────────────────────
        score = (
            config.WEIGHT_CYCLE       * cycle_p     +
            config.WEIGHT_COMPRESSION * compress_p  +
            config.WEIGHT_ENERGY      * energy_p
        )
        score = round(min(score, 1.0), 4)

        # Confidence = fraction of the score driven by the proven cycle component.
        # 1.0 = decision is entirely cycle-driven (most trustworthy)
        # 0.5 = cycle and unproven signals contribute equally (less trustworthy)
        cycle_contribution = config.WEIGHT_CYCLE * cycle_p
        confidence = round(cycle_contribution / (score + 1e-9), 4)
        confidence = min(confidence, 1.0)

        breakdown = {
            "cycle_p":     round(cycle_p,     4),
            "compress_p":  round(compress_p,  4),
            "energy_p":    round(energy_p,    4),
            "score":       score,
            "confidence":  confidence,
        }

        return score, confidence, breakdown

    # ─────────────────────────────────────────────────────────────────────────
    #  MAIN ANALYSIS
    # ─────────────────────────────────────────────────────────────────────────

    def analyze_ticks(self, prices: list[float]) -> tuple[str, dict]:
        """
        Analyzes raw tick buffer. Returns (decision, analytics_dict).
        Decision: "BUY" | "SELL" | "HOLD"

        analytics_dict now includes:
          spike_probability_pct  — composite spike probability as a percentage
          confidence_score       — how much of the score comes from the proven cycle signal
          score_breakdown        — per-component score values for debugging
        """
        if len(prices) < config.TICK_WINDOW_SIZE:
            return "HOLD", {"reason": "Warming up tick queue..."}

        # 1. Technical indicators
        features = ml_features.extract_all_features(prices, config.TICK_WINDOW_SIZE)

        # 2. Spike detection (current tick vs rolling average change)
        tick_changes    = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
        avg_tick_change = sum(tick_changes) / len(tick_changes) if tick_changes else 0.0001
        last_change     = prices[-1] - prices[-2]

        is_current_spike = False
        if self.is_boom  and last_change >  avg_tick_change * self.spike_threshold_factor:
            is_current_spike = True
        elif self.is_crash and last_change < -avg_tick_change * self.spike_threshold_factor:
            is_current_spike = True

        features["is_current_spike"] = is_current_spike
        features["avg_tick_change"]  = avg_tick_change
        features["last_change"]      = last_change

        # 3. Volatility squeeze flag (used by scoring component)
        is_squeezed = features["compression_ratio"] < config.SQUEEZE_THRESHOLD
        features["is_squeezed"] = is_squeezed

        # 4. Directional energy (last 10 ticks)
        recent     = prices[-10:]
        down_ticks = sum(1 for i in range(1, len(recent)) if recent[i] < recent[i-1])
        up_ticks   = len(recent) - 1 - down_ticks
        features["recent_down_ticks"] = down_ticks
        features["recent_up_ticks"]   = up_ticks

        # 5. Cycle state (increment BEFORE checking spike — spike resets it below)
        self.ticks_since_last_spike += 1
        cycle_mult, cycle_zone = self._compute_cycle_state()

        features["ticks_since_spike"] = self.ticks_since_last_spike
        features["cycle_position"]    = round(
            self.ticks_since_last_spike / config.SPIKE_CYCLE_LENGTH, 3
        )
        features["cycle_multiplier"]  = cycle_mult
        features["cycle_zone"]        = cycle_zone

        # Lot scale passed to trader for position sizing
        if config.CYCLE_LOT_SCALING and cycle_mult > 1.0:
            lot_scale = round(min(cycle_mult, config.CYCLE_MAX_LOT_SCALE), 3)
        else:
            lot_scale = 1.0
        features["cycle_lot_scale"] = lot_scale

        # 6. Spike on this tick → reset cycle counter, do not enter
        if is_current_spike:
            self.ticks_since_last_spike = 0
            self.total_spikes_observed += 1
            features["decision_reason"]       = (
                f"Spike detected! Counter reset. "
                f"Total spikes observed: {self.total_spikes_observed}"
            )
            features["spike_probability_pct"] = 0.0
            features["confidence_score"]      = 0.0
            return "HOLD", features

        # 7. Compute probability score
        score, confidence, breakdown = self._compute_spike_probability(
            features, down_ticks, up_ticks
        )

        features["spike_probability_pct"] = round(score * 100, 1)
        features["confidence_score"]      = round(confidence * 100, 1)
        features["score_breakdown"]       = breakdown

        # ── Entry Decision ────────────────────────────────────────────────────

        # Hard block: RECOVERY — spike probability has reset to near zero
        if cycle_zone == "RECOVERY":
            features["decision_reason"] = (
                f"RECOVERY zone — {self.ticks_since_last_spike} ticks since spike "
                f"(score {score*100:.1f}%, need {int(config.SPIKE_CYCLE_LENGTH * config.CYCLE_EARLY_ZONE)} "
                f"ticks before entries reopen)"
            )
            return "HOLD", features

        # Hard trigger: OVERDUE — past expected cycle point, enter unconditionally
        if cycle_zone == "OVERDUE":
            direction = "BUY" if self.is_boom else "SELL"
            features["decision_reason"] = (
                f"CYCLE OVERDUE — {self.ticks_since_last_spike} ticks without spike | "
                f"Score {score*100:.1f}% | "
                f"Cycle_p {breakdown['cycle_p']*100:.1f}% | "
                f"Conf {confidence*100:.0f}%"
            )
            return direction, features

        # Score-threshold entry: BUILDING and HOT zones
        if score >= config.ENTRY_SCORE_THRESHOLD:
            direction = "BUY" if self.is_boom else "SELL"
            features["decision_reason"] = (
                f"Score {score*100:.1f}% ≥ {config.ENTRY_SCORE_THRESHOLD*100:.0f}% threshold | "
                f"Cycle {self.ticks_since_last_spike}tk "
                f"({breakdown['cycle_p']*100:.1f}%) "
                f"Compress {breakdown['compress_p']*100:.0f}% "
                f"Energy {breakdown['energy_p']*100:.0f}% "
                f"[{cycle_zone}] Conf {confidence*100:.0f}%"
            )
            return direction, features

        # Below threshold — hold
        features["decision_reason"] = (
            f"Score {score*100:.1f}% < {config.ENTRY_SCORE_THRESHOLD*100:.0f}% threshold | "
            f"Cycle {self.ticks_since_last_spike}tk "
            f"({breakdown['cycle_p']*100:.1f}%) [{cycle_zone}]"
        )
        return "HOLD", features
