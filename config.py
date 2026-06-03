# config.py
"""
Synthetic Indices Trading Agent Configuration Module
Contains general settings, risk controls, and technical parameters for Crash / Boom markets.
"""

import os

# --- DERIV API CONNECTION ---
APP_ID = 1089
DERIV_TOKEN = os.getenv("DERIV_API_TOKEN", "")

# --- TRADING SYMBOLS ---
# BOOM1000 = avg 1 upward spike per 1000 ticks (~16 min)
# CRASH1000 = avg 1 downward spike per 1000 ticks
# BOOM500 = avg 1 upward spike per 500 ticks (~8 min)
# CRASH500 = avg 1 downward spike per 500 ticks
ACTIVE_SYMBOL = "BOOM1000"

# --- SIMULATION & PAPER TRADING ---
INITIAL_BALANCE = 1000.0
MIN_LOT_SIZE = 0.20
DEFAULT_LOT_SIZE = 1.0

# --- BOT EXIT PARAMETERS (TICK-BASED EXIT) ---
# BOOM1000 fires ~1 spike per 1000 ticks. Holding 80 ticks gives a reasonable
# window while keeping per-trade risk bounded.
BOOM_EXIT_TICKS = 80
CRASH_EXIT_TICKS = 80

# --- STOP LOSS / TAKE PROFIT (in price points) ---
# Exit immediately if trade moves this many points against us.
# BOOM1000 tick noise is ~0.01-0.20 pts; stop at 2.5 to avoid noise-outs.
STOP_LOSS_POINTS = 2.5
# Lock in profits early if spike gives us this many points.
TAKE_PROFIT_POINTS = 12.0

# --- BASELINE SPIKE STRATEGY HYPERPARAMETERS ---
TICK_WINDOW_SIZE = 50
VOLATILITY_COMPRESSION_WINDOW = 20
VOLATILITY_BOLLINGER_DEV = 1.5

# Spike threshold: a move > 3.0x mean tick change is flagged as a spike.
# Lowered from 4.5 → 3.0 to catch real BOOM spikes more reliably.
SPIKE_THRESHOLD_FACTOR = 3.0

# --- ENTRY FILTER THRESHOLDS ---
# RSI thresholds for entry signals
RSI_OVERSOLD = 35        # BOOM entry: buy when RSI < 35 (was 30 — too rare)
RSI_OVERBOUGHT = 65      # CRASH entry: sell when RSI > 65 (was 70 — too rare)

# Squeeze compression ratio threshold (< this = market is coiling)
SQUEEZE_THRESHOLD = 0.80  # was 0.75 — slightly more generous

# Z-score threshold for squeeze + slope entry
ZSCORE_ENTRY = 1.0        # was 1.2 — trigger slightly earlier

# --- RISK MANAGEMENT LIMITS ---
MAX_DAILY_LOSS = 50.0
MAX_TRADES_PER_SESSION = 50
COOLDOWN_AFTER_LOSS_STREAK = 5    # was 3 — allow 5 losses before cooldown
COOLDOWN_MINUTES = 3              # was 30 — 3-minute breather, not 30
MAX_DRAWDOWN_PCT = 0.15           # was 0.10 — 15% max drawdown (more room)

# --- FILE PATHS FOR LOGGING ---
LOG_DIR = "logs"
TRADE_LOG_CSV = os.path.join(LOG_DIR, "trade_log.csv")
TRADE_LOG_JSON = os.path.join(LOG_DIR, "trade_log.json")
BOT_METRICS_JSON = os.path.join(LOG_DIR, "bot_metrics.json")
