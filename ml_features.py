# ml_features.py
"""
ML Features Engineering Module
Extracts high-fidelity real-time quantitative features from live tick sequences.
Designed so rule-based elements can be swapped for pre-trained ML models later.

Bug fixed (v2): calculate_ema_gradient() previously used a loop with a dead
`else prices` branch — the "current" EMA was computed on prices[:-1] (one tick
stale). Now uses three explicit price slices: prices[:-2], prices[:-1], prices.
"""

import math


def calculate_sma(prices: list[float], window: int) -> float:
    """Simple Moving Average over a price window."""
    if len(prices) < window:
        window = len(prices)
    if window == 0:
        return 0.0
    return sum(prices[-window:]) / window


def calculate_ema(prices: list[float], window: int) -> float:
    """Exponential Moving Average over a price window."""
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
    """Standard deviation (volatility) over a historical window."""
    if len(prices) < window:
        window = len(prices)
    if window < 2:
        return 0.0
    subset   = prices[-window:]
    mean     = sum(subset) / len(subset)
    variance = sum((x - mean) ** 2 for x in subset) / (len(subset) - 1)
    return math.sqrt(variance)


def calculate_rsi(prices: list[float], window: int = 14) -> float:
    """Relative Strength Index over tick price movements."""
    if len(prices) < window + 1:
        return 50.0   # neutral default during warmup

    gains  = []
    losses = []
    for i in range(len(prices) - window, len(prices)):
        diff = prices[i] - prices[i - 1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(diff))

    avg_gain = sum(gains)  / window
    avg_loss = sum(losses) / window

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calculate_momentum(prices: list[float], period: int = 5) -> float:
    """Rate of change (momentum) over N steps."""
    if len(prices) < period + 1:
        return 0.0
    return prices[-1] - prices[-(period + 1)]


def calculate_ema_gradient(prices: list[float], window: int = 10) -> float:
    """
    EMA slope — average change in EMA over the last 2 steps.

    Fix v2: The original implementation used a loop `for i in range(3, 0, -1)`
    with a dead `else prices` branch, so the "current" EMA was always computed
    on prices[:-1] (one tick stale). Now uses three explicit slices so the
    current tick is always included.

    Returns (EMA_current - EMA_2ticks_ago) / 2  — average per-tick EMA change.
    """
    if len(prices) < window + 3:
        return 0.0

    ema_two_ago = calculate_ema(prices[:-2], window)   # 2 ticks back
    ema_one_ago = calculate_ema(prices[:-1], window)   # 1 tick back
    ema_current = calculate_ema(prices,      window)   # current tick

    # Linear slope: average over the two most recent EMA steps
    slope = (ema_current - ema_two_ago) / 2.0
    return slope


def extract_all_features(prices: list[float], window: int = 30) -> dict:
    """
    Produces the full feature vector from a raw tick buffer.
    All downstream consumers (strategy.py, backtester.py) call this function
    so that live trading and backtesting always use identical calculations.
    """
    if not prices:
        return {}

    current_price = prices[-1]
    sma_fast      = calculate_sma(prices, 5)
    sma_slow      = calculate_sma(prices, window)
    std_dev_slow  = calculate_std_dev(prices, window)
    std_dev_fast  = calculate_std_dev(prices, 5)
    rsi_val       = calculate_rsi(prices, 14)
    momentum_fast = calculate_momentum(prices, 5)

    # Z-score: distance from rolling mean in std-dev units
    z_score = (current_price - sma_slow) / std_dev_slow if std_dev_slow > 0 else 0.0

    # Compression ratio: fast std / slow std
    # < SQUEEZE_THRESHOLD → volatility is compressing (possible coil before spike)
    compression_ratio = std_dev_fast / std_dev_slow if std_dev_slow > 0 else 1.0

    # EMA gradient (fixed: now uses prices, prices[:-1], prices[:-2] explicitly)
    ema_slope = calculate_ema_gradient(prices, 10)

    # Micro-volatility: std over last 2 ticks (captures sudden small bursts)
    micro_std = calculate_std_dev(prices, 2)

    return {
        "current_price":    current_price,
        "rolling_mean":     sma_slow,
        "rolling_std_dev":  std_dev_slow,
        "std_dev_fast":     std_dev_fast,
        "z_score":          z_score,
        "rsi":              rsi_val,
        "momentum":         momentum_fast,
        "compression_ratio": compression_ratio,
        "sma_diff":         sma_fast - sma_slow,
        "ema_slope":        ema_slope,
        "micro_std":        micro_std,
    }
