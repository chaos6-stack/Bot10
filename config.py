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
BOOM_EXIT_TICKS = 120
CRASH_EXIT_TICKS = 120

# --- STOP LOSS / TAKE PROFIT (in price points) ---
STOP_LOSS_POINTS = 4.0
TAKE_PROFIT_POINTS = 20.0

# --- BASELINE SPIKE STRATEGY HYPERPARAMETERS ---
TICK_WINDOW_SIZE = 50
VOLATILITY_COMPRESSION_WINDOW = 20
VOLATILITY_BOLLINGER_DEV = 1.5
SPIKE_THRESHOLD_FACTOR = 3.0

# --- ENTRY FILTER THRESHOLDS ---
RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 58
SQUEEZE_THRESHOLD = 0.75
ZSCORE_ENTRY = 0.8

# --- SPIKE CYCLE COUNTER ---
# BOOM1000 fires ~1 spike per 1000 ticks. We track how many ticks have
# passed since the last observed spike and use that to scale entry
# aggressiveness — entering more boldly when a spike is statistically overdue.
#
# Zones (as a fraction of SPIKE_CYCLE_LENGTH):
#   RECOVERY  0.00 – CYCLE_EARLY_ZONE   No entries. Spike just happened;
#                                        probability has reset to near zero.
#   BUILDING  CYCLE_EARLY_ZONE – CYCLE_HOT_ZONE   Normal signals apply.
#   HOT       CYCLE_HOT_ZONE – 1.00    Spike is approaching statistically.
#                                        Normal signals + relaxed thresholds.
#   OVERDUE   > 1.00                    Past expected cycle point. Enter
#                                        even without other confirmations.
SPIKE_CYCLE_LENGTH = 1000       # ticks between spikes (matches index name)
CYCLE_EARLY_ZONE = 0.25         # recovery zone ends at 25% of cycle
CYCLE_HOT_ZONE = 0.70           # hot zone begins at 70% of cycle

# Lot size scaling when a spike is overdue (CYCLE_LOT_SCALING must be True).
# At cycle_multiplier = 2.0 (furthest overdue) lot size = DEFAULT_LOT_SIZE * 2.0
CYCLE_LOT_SCALING = True
CYCLE_MAX_LOT_SCALE = 2.0

# --- RISK MANAGEMENT LIMITS ---
MAX_DAILY_LOSS = 50.0
MAX_TRADES_PER_SESSION = 50
COOLDOWN_AFTER_LOSS_STREAK = 5
COOLDOWN_MINUTES = 3
MAX_DRAWDOWN_PCT = 0.15

# --- FILE PATHS FOR LOGGING ---
LOG_DIR = "logs"
TRADE_LOG_CSV = os.path.join(LOG_DIR, "trade_log.csv")
TRADE_LOG_JSON = os.path.join(LOG_DIR, "trade_log.json")
BOT_METRICS_JSON = os.path.join(LOG_DIR, "bot_metrics.json")
