# strategy.py
"""
Spike Trading Strategy Engine (Crash/Boom Specifics)
Implements statistical logic to detect low-volatility price compression
and breakout conditions, which signal high probability of spikes.
"""

import ml_features
import config

class SpikeStrategy:
    def __init__(self, symbol: str = config.ACTIVE_SYMBOL):
        self.symbol = symbol.upper()
        self.is_boom = "BOOM" in self.symbol
        self.is_crash = "CRASH" in self.symbol
        self.spike_threshold_factor = config.SPIKE_THRESHOLD_FACTOR

    def analyze_ticks(self, prices: list[float]) -> tuple[str, dict]:
        """
        Analyzes raw tick streams. Returns (decision, analytics_dict).
        Decision is one of: "BUY", "SELL", "HOLD"
        """
        if len(prices) < config.TICK_WINDOW_SIZE:
            return "HOLD", {"reason": "Warming up tick queue..."}

        # 1. Extract features
        features = ml_features.extract_all_features(prices, config.TICK_WINDOW_SIZE)

        # 2. Spike detection on current tick
        tick_changes = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
        avg_tick_change = sum(tick_changes) / len(tick_changes) if tick_changes else 0.0001
        last_change = prices[-1] - prices[-2]

        is_current_spike = False
        if self.is_boom and last_change > (avg_tick_change * self.spike_threshold_factor):
            is_current_spike = True
        elif self.is_crash and last_change < -(avg_tick_change * self.spike_threshold_factor):
            is_current_spike = True

        features["is_current_spike"] = is_current_spike
        features["avg_tick_change"] = avg_tick_change
        features["last_change"] = last_change

        # 3. Volatility squeeze check
        is_squeezed = features["compression_ratio"] < config.SQUEEZE_THRESHOLD
        features["is_squeezed"] = is_squeezed

        # 4. Consecutive tick direction analysis (energy build-up)
        # Count recent consecutive down-ticks (for BOOM) — the more, the closer to spike
        recent = prices[-10:]
        down_ticks = sum(1 for i in range(1, len(recent)) if recent[i] < recent[i-1])
        up_ticks = len(recent) - 1 - down_ticks
        features["recent_down_ticks"] = down_ticks
        features["recent_up_ticks"] = up_ticks

        # 5. Decision Logic
        decision = "HOLD"
        reason = "Market neutral"

        if self.is_boom:
            slope_positive = features["ema_slope"] > 0
            slope_flat_or_up = features["ema_slope"] >= -0.005  # loosened: allow flat slope
            micro_spike_warning = features["micro_std"] > (features["rolling_std_dev"] * 0.6)  # was 0.8

            # Signal A: Classic oversold — RSI well below threshold
            if features["rsi"] < config.RSI_OVERSOLD:
                decision = "BUY"
                reason = f"RSI oversold ({features['rsi']:.1f}) — mean reversion expected"

            # Signal B: Volatility squeeze with z-score breakdown and slope turning up
            elif is_squeezed and (features["z_score"] < -config.ZSCORE_ENTRY) and slope_flat_or_up:
                decision = "BUY"
                reason = f"Squeeze coil + Z-score {features['z_score']:.2f} — breakout setup"

            # Signal C: Momentum burst with micro-volatility expanding (early spike warning)
            elif (features["momentum"] > 0) and slope_positive and micro_spike_warning:
                decision = "BUY"
                reason = "Momentum + micro-volatility breakout signal"

            # Signal D: Deep downtrend energy build (BOOM-specific: 8 of last 10 ticks down)
            elif down_ticks >= 8 and is_squeezed:
                decision = "BUY"
                reason = f"Energy build-up: {down_ticks}/10 ticks down, squeeze active"

        elif self.is_crash:
            slope_negative = features["ema_slope"] < 0
            slope_flat_or_down = features["ema_slope"] <= 0.005
            micro_spike_warning = features["micro_std"] > (features["rolling_std_dev"] * 0.6)

            if features["rsi"] > config.RSI_OVERBOUGHT:
                decision = "SELL"
                reason = f"RSI overbought ({features['rsi']:.1f}) — mean reversion expected"

            elif is_squeezed and (features["z_score"] > config.ZSCORE_ENTRY) and slope_flat_or_down:
                decision = "SELL"
                reason = f"Squeeze coil + Z-score {features['z_score']:.2f} — breakdown setup"

            elif (features["momentum"] < 0) and slope_negative and micro_spike_warning:
                decision = "SELL"
                reason = "Momentum + micro-volatility breakdown signal"

            elif up_ticks >= 8 and is_squeezed:
                decision = "SELL"
                reason = f"Energy build-up: {up_ticks}/10 ticks up, squeeze active"

        features["decision_reason"] = reason
        return decision, features
