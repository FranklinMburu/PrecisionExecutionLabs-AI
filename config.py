import os
from dotenv import load_dotenv

load_dotenv()

# MT5 CREDENTIALS
MT5_LOGIN = int(os.getenv("MT5_LOGIN", 0))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")
SYMBOL = os.getenv("MT5_SYMBOL", "XAUUSD")

RANGE_LOOKBACK = 6
BUFFER_POINTS = 60
MAGIC_NUMBER = 123456
LOOP_SLEEP = 0.5

# RISK CONTROLS
RISK_PER_TRADE = 0.02          # 2% per trade
SLIPPAGE_RISK_BUFFER = 1.2     # Account for 20% extra risk due to slippage/gaps
MAX_TOTAL_EXPOSURE = 0.05      # 5% max open risk
DAILY_LOSS_LIMIT = 0.08        # 8% stop trading

# VALIDATION LAYER
MAX_DRAWDOWN_STOP = 0.15       # 15% Hard stop
SOFT_DRAWDOWN_LIMIT = 0.10     # 10% Risk reduction
MIN_EXPECTANCY_THRESHOLD = 0.0 # Must be positive
VALIDATION_WINDOW = 30         # First check trades
CYCLE_WINDOW = 50              # Recurring check trades
STUCK_POSITION_THRESHOLD = 5   # Max retries before emergency evacuation

# MARKET FILTERS
MIN_RANGE_POINTS = 200         # Filter out "dead" markets
MAX_SPREAD_RATIO = 0.2         # Max spread as % of range
MAX_FRICTION_RATIO = 0.15      # Max spread as % of TP distance
MIN_R_MULTIPLE = 3             # Reward must be at least 3x spread
PENDING_EXPIRY_SEC_TTL = 3600  # 1 hour expiry for pending orders
RANGE_SHRINK_CHECK_WINDOW = 5  # Check for range compression
SHOCK_STABILIZATION_CYCLES = 5 # Minimum cycles to wait after shock
