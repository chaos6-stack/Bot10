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
        
        # Volatility & Compression limits
        self.spike_threshold_factor = config.SPIKE_THRESHOLD_FACTOR

    def analyze_ticks(self, prices: list[float]) -> tuple[str, dict]:
        """
        Analyzes raw tick streams. Returns (decision, analytics_dict).
        Decision is one of: "BUY", "SELL", "HOLD"
        """
        if len(prices) < config.TICK_WINDOW_SIZE:
            return "HOLD", {"reason": "Warming up tick queue..."}

        # 1. Extract technical indicator parameters using ML Feature module
        features = ml_features.extract_all_features(prices, config.TICK_WINDOW_SIZE)
        current_price = features["current_price"]
        
        # Calculate trailing tick-to-tick changes to assess noise level
        tick_changes = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
        avg_tick_change = sum(tick_changes) / len(tick_changes) if tick_changes else 0.0001
        
        # Read current tick movement
        last_change = prices[-1] - prices[-2]
        
        # 2. Check if a spike is happening *right now* mathematically
        is_current_spike = False
        if self.is_boom and last_change > (avg_tick_change * self.spike_threshold_factor):
            is_current_spike = True
        elif self.is_crash and last_change < -(avg_tick_change * self.spike_threshold_factor):
            is_current_spike = True

        features["is_current_spike"] = is_current_spike
        features["avg_tick_change"] = avg_tick_change
        features["last_change"] = last_change

        # 3. Decision Logic - Based on statistical anomalies & coils
        # In BOOM: Standard strategy is to BUY *before* a spike (e.g. support level, low-volatility squeeze, or RSI oversold)
        # In CRASH: Standard strategy is to SELL *before* a spike (RSI overbought, high z-score, low-volatility squeeze)
        decision = "HOLD"
        reason = "Market neutral"

        # Check for Volatility Squeeze (low standard deviation, coiling spring)
        # If standard dev compression ratio is < 0.70, it is compressed (ready to burst)
        is_squeezed = features["compression_ratio"] < 0.75
        features["is_squeezed"] = is_squeezed

        if self.is_boom:
            # We want to BUY.
            # Enhanced Conditions:
            # - EMA Slope is turning positive (rounding bottom)
            # - RSI is oversold
            # - Micro-volatility is starting to kick in (early spike warning)
            
            slope_positive = features["ema_slope"] > 0
            micro_spike_warning = features["micro_std"] > (features["rolling_std_dev"] * 0.8)

            if rsi_oversold := (features["rsi"] < 30):
                decision = "BUY"
                reason = "Oversold mean-reversion"
            elif is_squeezed and (features["z_score"] < -1.2) and slope_positive:
                decision = "BUY"
                reason = "Squeeze with positive slope"
            elif (features["momentum"] > 0) and slope_positive and micro_spike_warning:
                decision = "BUY"
                reason = "Momentum breakout confirmed"
                
        elif self.is_crash:
            # We want to SELL (short).
            slope_negative = features["ema_slope"] < 0
            micro_spike_warning = features["micro_std"] > (features["rolling_std_dev"] * 0.8)

            if rsi_overbought := (features["rsi"] > 70):
                decision = "SELL"
                reason = "Overbought mean-reversion"
            elif is_squeezed and (features["z_score"] > 1.2) and slope_negative:
                decision = "SELL"
                reason = "Squeeze with negative slope"
            elif (features["momentum"] < 0) and slope_negative and micro_spike_warning:
                decision = "SELL"
                reason = "Momentum breakout confirmed"

        features["decision_reason"] = reason
        return decision, features

