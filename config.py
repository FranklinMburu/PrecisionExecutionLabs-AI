import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def get_int_env(key, default):
    val = os.getenv(key, "")
    if val == "" or val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default

# MT5 CREDENTIALS
MT5_LOGIN = get_int_env("MT5_LOGIN", 0)
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")
MT5_SYMBOL = os.getenv("MT5_SYMBOL", "XAUUSD")
SYMBOL = MT5_SYMBOL
MAGIC_NUMBER = 123456
LOOP_SLEEP = 0.5

# RISK CONTROLS
RISK_PER_TRADE = 0.02          # 2% per trade
SLIPPAGE_RISK_BUFFER = 1.2     # Account for 20% extra risk due to slippage/gaps
MAX_TOTAL_EXPOSURE = 0.05      # 5% max open risk
DAILY_LOSS_LIMIT = 0.08        # 8% stop trading
MAX_DRAWDOWN_STOP = 0.15       # 15% Hard stop
SOFT_DRAWDOWN_LIMIT = 0.10     # 10% Risk reduction

# VALIDATION LAYER
MIN_EXPECTANCY_THRESHOLD = 0.0 # Must be positive
VALIDATION_WINDOW = 30         # First check trades
CYCLE_WINDOW = 50              # Recurring check trades
STUCK_POSITION_THRESHOLD = 5   # Max retries before emergency evacuation
EXPECTANCY_VALIDATION_WINDOW = 30

# STRATEGY TUNING
RANGE_LOOKBACK = 6
BUFFER_POINTS = 60
TP_RATIO = 3.0                 # Target 3R
TP_TRAILING_ENABLE = True
TP_TRAILING_START_R = 2.0      # When to start pushing TP further
TP_TRAILING_STEP_R = 1.0       # How much to push TP by

# INTELLIGENT TRAILING STOP SETTINGS
TRAILING_STOP_ENABLE = True
TRAILING_STOP_MODE = "FIXED"    # FIXED | PERCENTAGE | VOLATILITY
TRAILING_STOP_FIXED_POINTS = 150 # Distance in points (e.g. 150 points = 15 pips)
TRAILING_STOP_PERCENT = 0.001   # 0.1% distance
TRAILING_STOP_VOL_ATR_MULT = 1.5 # ATR Multiplier for volatility mode
TRAILING_STOP_MOMENTUM_SENSITIVITY = 0.5 # 0.0 - 1.0 (Higher = reacts faster to trend strength)
TRAILING_STOP_MIN_PROFIT_R = 0.5 # Only trail once we reached 0.5R profit
TRAILING_STOP_CONFIRMATION_MINUTES = 1 # High timeframe intelligence window
TRAILING_STOP_STEP_POINTS = 30  # Minimum movement to update broker SL (reduce API noise)

# MARKET FILTERS
MIN_RANGE_POINTS = 200         # Filter out "dead" markets
MAX_SPREAD_RATIO = 0.2         # Max spread as % of range
MAX_FRICTION_RATIO = 0.15      # Max spread as % of TP distance
SHOCK_STABILIZATION_CYCLES = 5 # Wait time after market shock
RANGE_SHRINK_CHECK_WINDOW = 5  # Check for range compression
PENDING_EXPIRY_SEC_TTL = 3600  # 1 hour expiry for pending orders
ROLLOVER_HOURS_UTC = [21, 22, 23]
MARKET_SHOCK_MULTIPLIER = 3.0
