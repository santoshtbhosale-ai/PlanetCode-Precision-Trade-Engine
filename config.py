import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')

DHAN_CLIENT_ID = os.getenv('DHAN_CLIENT_ID', '').strip()
DHAN_ACCESS_TOKEN = os.getenv('DHAN_ACCESS_TOKEN', '').strip()
NIFTY_SECURITY_ID = int(os.getenv('NIFTY_SECURITY_ID', '13'))
BANKNIFTY_SECURITY_ID = int(os.getenv('BANKNIFTY_SECURITY_ID', '25'))
UNDERLYING_SEGMENT = os.getenv('UNDERLYING_SEGMENT', 'IDX_I')
MIN_SETUP_SCORE = int(os.getenv('MIN_SETUP_SCORE', '78'))
CHOPPY_MIN_SCORE = int(os.getenv('CHOPPY_MIN_SCORE', '85'))
STRONG_TREND_MIN_SCORE = int(os.getenv('STRONG_TREND_MIN_SCORE', '75'))
OPTION_STRIKE_RANGE = int(os.getenv('OPTION_STRIKE_RANGE', '4'))
MAX_OPTION_SPREAD_PCT = float(os.getenv('MAX_OPTION_SPREAD_PCT', '1.5'))
OPTION_CHAIN_CACHE_SECONDS = float(os.getenv('OPTION_CHAIN_CACHE_SECONDS', '3'))
AUTO_SCAN_SECONDS = int(os.getenv('AUTO_SCAN_SECONDS', '15'))
CAPITAL = float(os.getenv('CAPITAL', '100000'))
RISK_PCT = float(os.getenv('RISK_PCT', '0.50'))
MAX_SIGNALS_PER_DAY = int(os.getenv('MAX_SIGNALS_PER_DAY', '5'))
SIGNAL_COOLDOWN_SECONDS = int(os.getenv('SIGNAL_COOLDOWN_SECONDS', '180'))
STALE_DATA_SECONDS = int(os.getenv('STALE_DATA_SECONDS', '20'))
WEBSOCKET_ENABLED = os.getenv('DHAN_ENABLE_WEBSOCKET', 'true').lower() in {'1','true','yes','y'}
LOT_SIZE_FALLBACK = int(os.getenv('LOT_SIZE_FALLBACK', '65'))
INSTRUMENT_MASTER_URL = os.getenv('INSTRUMENT_MASTER_URL', 'https://images.dhan.co/api-data/api-scrip-master.csv')
TRADING_START_TIME = os.getenv('TRADING_START_TIME', '09:20')
TRADING_END_TIME = os.getenv('TRADING_END_TIME', '15:15')
MIN_RR = float(os.getenv('MIN_RR', '2.0'))
MAX_PREMIUM_BUDGET_PCT = float(os.getenv('MAX_PREMIUM_BUDGET_PCT', '10'))
PAPER_MODE = os.getenv('TRADING_MODE', 'MANUAL').upper() == 'PAPER'

# Historical/news validation gates. These are validation thresholds, not guarantees.
HISTORICAL_VALIDATION_ENABLED = os.getenv('HISTORICAL_VALIDATION_ENABLED', 'true').lower() in {'1','true','yes','y'}
HISTORICAL_LOOKBACK_DAYS = int(os.getenv('HISTORICAL_LOOKBACK_DAYS', '60'))
HISTORICAL_MIN_SAMPLES = int(os.getenv('HISTORICAL_MIN_SAMPLES', '20'))
HISTORICAL_MIN_HIT_RATE = float(os.getenv('HISTORICAL_MIN_HIT_RATE', '80'))
NEWS_VALIDATION_ENABLED = os.getenv('NEWS_VALIDATION_ENABLED', 'true').lower() in {'1','true','yes','y'}
NEWS_MAX_AGE_HOURS = int(os.getenv('NEWS_MAX_AGE_HOURS', '12'))
NEWS_RISK_BLOCK = os.getenv('NEWS_RISK_BLOCK', 'true').lower() in {'1','true','yes','y'}

