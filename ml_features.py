# ml_features.py
"""
ML Features Engineering Module
Extracts high-fidelity real-time quantitative features from live tick sequences.
Designed so that rule-based elements can be naturally swapped for pre-trained ML models (PyTorch/Scikit-Learn).
"""

import math

def calculate_sma(prices: list[float], window: int) -> float:
    """Calculates Simple Moving Average over a price window."""
    if len(prices) < window:
        window = len(prices)
    if window == 0:
        return 0.0
    return sum(prices[-window:]) / window

def calculate_ema(prices: list[float], window: int) -> float:
    """Calculates Exponential Moving Average over a price window."""
    if not prices:
        return 0.0
    if len(prices) == 1:
        return prices[0]
    
    alpha = 2.0 / (window + 1.0)
    ema = prices[0]
    for p in prices[1:]:
        ema = alpha * p + (1.0 - alpha) * ema
    return ema

def calculate_std_dev(prices: list[float], window: int) -> float:
    """Calculates standard deviation (volatility metric) over a historical window."""
    if len(prices) < window:
        window = len(prices)
    if window < 2:
        return 0.0
    
    subset = prices[-window:]
    mean = sum(subset) / len(subset)
    variance = sum((x - mean) ** 2 for x in subset) / (len(subset) - 1)
    return math.sqrt(variance)

def calculate_rsi(prices: list[float], window: int = 14) -> float:
    """Calculates Relative Strength Index over tick price movements."""
    if len(prices) < window + 1:
        return 50.0  # Neutral state default
    
    gains = []
    losses = []
    for i in range(len(prices) - window, len(prices)):
        diff = prices[i] - prices[i - 1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(diff))
            
    avg_gain = sum(gains) / window
    avg_loss = sum(losses) / window
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def calculate_momentum(prices: list[float], period: int = 5) -> float:
    """Calculates rate of change (momentum) over N steps."""
    if len(prices) < period + 1:
        return 0.0
    return prices[-1] - prices[-(period + 1)]

def calculate_ema_gradient(prices: list[float], window: int = 10) -> float:
    """Calculates the slope/gradient of the EMA over the last 3 steps."""
    if len(prices) < window + 3:
        return 0.0
    
    ema_vals = []
    for i in range(3, 0, -1):
        subset = prices[:-i] if i > 0 else prices
        ema_vals.append(calculate_ema(subset, window))
        
    # Simple linear slope: (y2 - y1) / (x2 - x1)
    # We use the average of the last two changes
    slope = (ema_vals[2] - ema_vals[0]) / 2.0
    return slope

def extract_all_features(prices: list[float], window: int = 30) -> dict:
    """
    Analyzes historical tick list to parse standard feature vector.
    Yields highly organized indicators ready for prediction engines.
    """
    if not prices:
        return {}
        
    current_price = prices[-1]
    sma_fast = calculate_sma(prices, 5)
    sma_slow = calculate_sma(prices, window)
    std_dev_slow = calculate_std_dev(prices, window)
    rsi_slow = calculate_rsi(prices, 14)
    momentum_fast = calculate_momentum(prices, 5)
    
    # Z-Score: how far is the price from its rolling historical average
    if std_dev_slow > 0:
        z_score = (current_price - sma_slow) / std_dev_slow
    else:
        z_score = 0.0
        
    # Volatility squeeze: ratio of fast standard dev vs slow standard dev (compression)
    std_dev_fast = calculate_std_dev(prices, 5)
    compression_ratio = std_dev_fast / std_dev_slow if std_dev_slow > 0 else 1.0

    # NEW: EMA Gradient (Slope)
    ema_slope = calculate_ema_gradient(prices, 10)

    # NEW: Micro-Volatility (2-tick window)
    micro_std = calculate_std_dev(prices, 2)

    return {
        "current_price": current_price,
        "rolling_mean": sma_slow,
        "rolling_std_dev": std_dev_slow,
        "std_dev_fast": std_dev_fast,
        "z_score": z_score,
        "rsi": rsi_slow,
        "momentum": momentum_fast,
        "compression_ratio": compression_ratio,
        "sma_diff": sma_fast - sma_slow,
        "ema_slope": ema_slope,
        "micro_std": micro_std
    }

