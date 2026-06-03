# config.py
"""
Synthetic Indices Trading Agent Configuration Module
Contains general settings, risk controls, and technical parameters for Crash / Boom markets.
"""

import os

# --- DERIV API CONNECTION ---
APP_ID = 1089  # Default trade app ID for public use
# For real trading, replace with user API token from Deriv portal
DERIV_TOKEN = os.getenv("DERIV_API_TOKEN", "")

# --- TRADING SYMBOLS ---
# Popular synthetic index symbols:
# 'BOOM1000' -> 'R_BOOM1000' / 'BOOM1000'
# 'CRASH1000' -> 'R_CRASH1000' / 'CRASH1000'
# 'BOOM500' -> 'R_BOOM500' / 'BOOM500'
# 'CRASH500' -> 'R_CRASH500' / 'CRASH500'
ACTIVE_SYMBOL = "BOOM1000"  # Options: BOOM1000, CRASH1000, BOOM500, CRASH500

# --- SIMULATION & PAPER TRADING ---
INITIAL_BALANCE = 1000.0   # USD virtual balance
MIN_LOT_SIZE = 0.20        # Standard lot sizes on Deriv (0.2 lots for Boom/Crash)
DEFAULT_LOT_SIZE = 1.0     # Default simulation lot size

# --- BOT EXIT PARAMETERS (TICK-BASED EXIT) ---
# In Boom/Crash, traders typically exit after N ticks if no spike occurs
BOOM_EXIT_TICKS = 10       # Hold trade for 10 ticks hoping for a spike, then exit if empty
CRASH_EXIT_TICKS = 10

# --- BASELINE SPIKE STRATEGY HYPERPARAMETERS ---
TICK_WINDOW_SIZE = 50      # Historical ticks memory size for calculating metrics
VOLATILITY_COMPRESSION_WINDOW = 20
VOLATILITY_BOLLINGER_DEV = 1.8  # Standard deviation threshold for compression

# A spike is a sudden price movement that rises (Boom) or drops (Crash) rapidly.
# Defining standard spike multiples (deviation multiplier of the current tick range)
SPIKE_THRESHOLD_FACTOR = 4.5  # If tick change is > this multiple of mean change, it's a spike!

# --- RISK MANAGEMENT LIMITS (CRITICAL CONTROLS) ---
MAX_DAILY_LOSS = 50.0       # USD maximum allowed daily loss before stopping bot
MAX_TRADES_PER_SESSION = 20 # Protects against over-trading and loops
COOLDOWN_AFTER_LOSS_STREAK = 3  # Disable trading for 30 minutes after 3 consecutive losses
COOLDOWN_MINUTES = 30
MAX_DRAWDOWN_PCT = 0.10     # Max account drawdown (10%) before hard stop

# --- FILE PATHS FOR LOGGING ---
LOG_DIR = "logs"
TRADE_LOG_CSV = os.path.join(LOG_DIR, "trade_log.csv")
TRADE_LOG_JSON = os.path.join(LOG_DIR, "trade_log.json")
BOT_METRICS_JSON = os.path.join(LOG_DIR, "bot_metrics.json")

