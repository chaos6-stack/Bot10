# strategy.py
"""
Spike Trading Strategy Engine (Crash/Boom Specifics)
Implements statistical logic to detect low-volatility price compression,
breakout conditions, and spike cycle positioning — all of which signal
elevated probability of an imminent spike.
"""

import ml_features
import config


class SpikeStrategy:
    def __init__(self, symbol: str = config.ACTIVE_SYMBOL):
        self.symbol = symbol.upper()
        self.is_boom  = "BOOM"  in self.symbol
        self.is_crash = "CRASH" in self.symbol
        self.spike_threshold_factor = config.SPIKE_THRESHOLD_FACTOR

        # ── Spike Cycle Counter ──────────────────────────────────────────
        # We start at 50% of the expected cycle length because we don't
        # know when the last spike was at startup. This puts us in the
        # BUILDING zone immediately rather than a false OVERDUE alarm.
        self.ticks_since_last_spike: int = config.SPIKE_CYCLE_LENGTH // 2
        self.total_spikes_observed: int  = 0

    # ─────────────────────────────────────────────────────────────────────
    #  CYCLE MULTIPLIER
    # ─────────────────────────────────────────────────────────────────────

    def _compute_cycle_state(self) -> tuple[float, str]:
        """
        Returns (multiplier, zone_label) based on ticks elapsed since the
        last observed spike.

        multiplier < 1.0  → suppress / normal entries
        multiplier = 1.0  → neutral (standard signals apply)
        multiplier > 1.0  → elevated: relax thresholds, scale lots

        Zone labels:  RECOVERY | BUILDING | HOT | OVERDUE
        """
        cycle_pos = self.ticks_since_last_spike / config.SPIKE_CYCLE_LENGTH
        early     = config.CYCLE_EARLY_ZONE   # e.g. 0.25
        hot       = config.CYCLE_HOT_ZONE     # e.g. 0.70

        if cycle_pos < early:
            # Spike just fired — probability has reset to near zero
            progress   = cycle_pos / early
            multiplier = 0.1 + progress * 0.4          # 0.10 → 0.50
            zone       = "RECOVERY"

        elif cycle_pos < hot:
            # Normal build-up phase
            progress   = (cycle_pos - early) / (hot - early)
            multiplier = 0.5 + progress * 0.5           # 0.50 → 1.00
            zone       = "BUILDING"

        elif cycle_pos < 1.0:
            # Approaching expected spike point
            progress   = (cycle_pos - hot) / (1.0 - hot)
            multiplier = 1.0 + progress * 0.75          # 1.00 → 1.75
            zone       = "HOT"

        else:
            # Past expected point — statistically overdue
            overage    = min((cycle_pos - 1.0) / 0.5, 1.0)
            multiplier = 1.75 + overage * 0.25          # 1.75 → 2.00
            zone       = "OVERDUE"

        return round(multiplier, 3), zone

    # ─────────────────────────────────────────────────────────────────────
    #  MAIN ANALYSIS
    # ─────────────────────────────────────────────────────────────────────

    def analyze_ticks(self, prices: list[float]) -> tuple[str, dict]:
        """
        Analyzes a raw tick buffer. Returns (decision, analytics_dict).
        Decision: "BUY" | "SELL" | "HOLD"
        """
        if len(prices) < config.TICK_WINDOW_SIZE:
            return "HOLD", {"reason": "Warming up tick queue..."}

        # 1. Technical indicators
        features = ml_features.extract_all_features(prices, config.TICK_WINDOW_SIZE)

        # 2. Spike detection (raw tick change vs mean change)
        tick_changes   = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
        avg_tick_change = sum(tick_changes) / len(tick_changes) if tick_changes else 0.0001
        last_change    = prices[-1] - prices[-2]

        is_current_spike = False
        if self.is_boom  and last_change >  avg_tick_change * self.spike_threshold_factor:
            is_current_spike = True
        elif self.is_crash and last_change < -avg_tick_change * self.spike_threshold_factor:
            is_current_spike = True

        features["is_current_spike"] = is_current_spike
        features["avg_tick_change"]  = avg_tick_change
        features["last_change"]      = last_change

        # 3. Volatility squeeze
        is_squeezed = features["compression_ratio"] < config.SQUEEZE_THRESHOLD
        features["is_squeezed"] = is_squeezed

        # 4. Recent directional energy (last 10 ticks)
        recent     = prices[-10:]
        down_ticks = sum(1 for i in range(1, len(recent)) if recent[i] < recent[i-1])
        up_ticks   = len(recent) - 1 - down_ticks
        features["recent_down_ticks"] = down_ticks
        features["recent_up_ticks"]   = up_ticks

        # 5. Cycle state — computed BEFORE we potentially reset the counter
        self.ticks_since_last_spike += 1
        cycle_mult, cycle_zone = self._compute_cycle_state()

        features["ticks_since_spike"] = self.ticks_since_last_spike
        features["cycle_position"]    = round(
            self.ticks_since_last_spike / config.SPIKE_CYCLE_LENGTH, 3
        )
        features["cycle_multiplier"]  = cycle_mult
        features["cycle_zone"]        = cycle_zone

        # Lot scale — passed to trader to size position dynamically
        if config.CYCLE_LOT_SCALING and cycle_mult > 1.0:
            lot_scale = round(min(cycle_mult, config.CYCLE_MAX_LOT_SCALE), 3)
        else:
            lot_scale = 1.0
        features["cycle_lot_scale"] = lot_scale

        # 6. If this tick IS a spike: reset cycle counter and hold
        #    (entering mid-spike is pointless — the move is already done)
        if is_current_spike:
            self.ticks_since_last_spike = 0
            self.total_spikes_observed += 1
            features["decision_reason"] = (
                f"Spike detected! Counter reset. "
                f"Total spikes observed: {self.total_spikes_observed}"
            )
            return "HOLD", features

        # 7. Entry decision
        decision = "HOLD"
        reason   = "Market neutral"

        # Shared indicator shortcuts
        slope_pos      = features["ema_slope"] > 0
        slope_flat_up  = features["ema_slope"] >= -0.005
        slope_neg      = features["ema_slope"] < 0
        slope_flat_dn  = features["ema_slope"] <= 0.005
        micro_warn     = features["micro_std"] > features["rolling_std_dev"] * 0.6

        # ── RECOVERY ZONE: block all new entries ──────────────────────────
        if cycle_zone == "RECOVERY":
            features["decision_reason"] = (
                f"Cycle recovery — {self.ticks_since_last_spike} ticks since spike, "
                f"waiting for {int(config.SPIKE_CYCLE_LENGTH * config.CYCLE_EARLY_ZONE)} tick mark"
            )
            return "HOLD", features

        # ── HOT/OVERDUE: relax entry thresholds ───────────────────────────
        # In hot/overdue zones we loosen RSI and z-score requirements so
        # the bot enters even on weaker setups — because a spike is due.
        rsi_threshold = config.RSI_OVERSOLD + (5 if cycle_zone in ("HOT", "OVERDUE") else 0)
        zs_threshold  = config.ZSCORE_ENTRY  * (0.7 if cycle_zone in ("HOT", "OVERDUE") else 1.0)

        if self.is_boom:
            # Signal A: RSI oversold
            if features["rsi"] < rsi_threshold:
                decision = "BUY"
                reason   = (
                    f"RSI oversold ({features['rsi']:.1f}) [{cycle_zone} zone, "
                    f"{self.ticks_since_last_spike} ticks]"
                )

            # Signal B: Volatility squeeze + z-score breakdown
            elif is_squeezed and features["z_score"] < -zs_threshold and slope_flat_up:
                decision = "BUY"
                reason   = (
                    f"Squeeze coil Z={features['z_score']:.2f} "
                    f"[{cycle_zone}, {self.ticks_since_last_spike} ticks]"
                )

            # Signal C: Momentum + micro-volatility burst
            elif features["momentum"] > 0 and slope_pos and micro_warn:
                decision = "BUY"
                reason   = f"Momentum breakout [{cycle_zone}, {self.ticks_since_last_spike} ticks]"

            # Signal D: Energy build-up (8/10 ticks down + squeezed)
            elif down_ticks >= 8 and is_squeezed:
                decision = "BUY"
                reason   = (
                    f"Energy build {down_ticks}/10 down [{cycle_zone}, "
                    f"{self.ticks_since_last_spike} ticks]"
                )

            # Signal E: Cycle overdue — enter regardless of other indicators
            elif cycle_zone == "OVERDUE":
                decision = "BUY"
                reason   = (
                    f"CYCLE OVERDUE — {self.ticks_since_last_spike} ticks "
                    f"without spike ({cycle_mult:.2f}x multiplier)"
                )

        elif self.is_crash:
            if features["rsi"] > (config.RSI_OVERBOUGHT - (5 if cycle_zone in ("HOT", "OVERDUE") else 0)):
                decision = "SELL"
                reason   = (
                    f"RSI overbought ({features['rsi']:.1f}) [{cycle_zone} zone, "
                    f"{self.ticks_since_last_spike} ticks]"
                )

            elif is_squeezed and features["z_score"] > zs_threshold and slope_flat_dn:
                decision = "SELL"
                reason   = (
                    f"Squeeze coil Z={features['z_score']:.2f} "
                    f"[{cycle_zone}, {self.ticks_since_last_spike} ticks]"
                )

            elif features["momentum"] < 0 and slope_neg and micro_warn:
                decision = "SELL"
                reason   = f"Momentum breakdown [{cycle_zone}, {self.ticks_since_last_spike} ticks]"

            elif up_ticks >= 8 and is_squeezed:
                decision = "SELL"
                reason   = (
                    f"Energy build {up_ticks}/10 up [{cycle_zone}, "
                    f"{self.ticks_since_last_spike} ticks]"
                )

            elif cycle_zone == "OVERDUE":
                decision = "SELL"
                reason   = (
                    f"CYCLE OVERDUE — {self.ticks_since_last_spike} ticks "
                    f"without spike ({cycle_mult:.2f}x multiplier)"
                )

        features["decision_reason"] = reason
        return decision, features
