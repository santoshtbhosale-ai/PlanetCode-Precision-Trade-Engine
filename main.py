from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from dhan_service import DhanService
from strategy import PrecisionEngine
from config import *

from datetime import datetime, time
from zoneinfo import ZoneInfo
from pathlib import Path


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="PlanetCode Precision Trade Engine V5.5"
)

# Always resolve templates relative to this file.
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"

t = Jinja2Templates(
    directory=str(TEMPLATES_DIR)
)

d = DhanService()
engine = PrecisionEngine()


# ============================================================
# GLOBAL STATE
# ============================================================

signal_history = {
    "NIFTY": [],
    "BANKNIFTY": []
}

last_action = {
    "NIFTY": None,
    "BANKNIFTY": None
}

last_signal_at = {
    "NIFTY": 0,
    "BANKNIFTY": 0
}


# ============================================================
# TIMEZONE
# ============================================================

IST = ZoneInfo("Asia/Kolkata")


def now_ist():
    """
    Always return current India time.
    Render servers commonly run in UTC, so never use
    naive datetime.now() for NSE timings.
    """
    return datetime.now(IST)


# ============================================================
# MARKET STATUS
# ============================================================

def market_status():

    now = now_ist()

    current_time = now.time()

    # NSE regular equity/index derivatives session
    market_open = (
        now.weekday() < 5
        and time(9, 15) <= current_time <= time(15, 40)
    )

    return {
        "open": market_open,
        "label": "MARKET OPEN" if market_open else "MARKET CLOSED",
        "time": now.strftime("%H:%M:%S"),
        "date": now.strftime("%Y-%m-%d"),
        "server_time_ist": now.strftime("%H:%M:%S"),
        "server_date_ist": now.strftime("%Y-%m-%d"),
        "timezone": "Asia/Kolkata"
    }


# ============================================================
# ENTRY WINDOW
# ============================================================

def entry_window_open():

    current_time = now_ist().time()

    start_hour, start_minute = map(
        int,
        TRADING_START_TIME.split(":")
    )

    end_hour, end_minute = map(
        int,
        TRADING_END_TIME.split(":")
    )

    start_time = time(
        start_hour,
        start_minute
    )

    end_time = time(
        end_hour,
        end_minute
    )

    return start_time <= current_time <= end_time


# ============================================================
# DAILY RESET
# ============================================================

signal_date = now_ist().date()


def reset_daily():

    global signal_date

    today = now_ist().date()

    if today != signal_date:

        signal_date = today

        for symbol in signal_history:
            signal_history[symbol] = []
            last_action[symbol] = None
            last_signal_at[symbol] = 0


# ============================================================
# RESULT GUARDS
# ============================================================

def guarded_result(symbol, result):

    reset_daily()

    now = now_ist()

    reasons = list(
        result.get("reasons", [])
    )

    action = result.get(
        "action",
        "NO TRADE"
    )

    status = market_status()

    # --------------------------------------------------------
    # MARKET CLOSED
    # --------------------------------------------------------

    if not status["open"]:

        result["action"] = "NO TRADE"
        result["quality"] = "MARKET CLOSED"

        reasons.append(
            "outside regular NSE market session"
        )

    # --------------------------------------------------------
    # ENTRY WINDOW CLOSED
    # --------------------------------------------------------

    elif not entry_window_open() and action.startswith("BUY"):

        result["action"] = "NO TRADE"
        result["quality"] = "ENTRY WINDOW CLOSED"

        reasons.append(
            f"fresh entries allowed only "
            f"{TRADING_START_TIME}-{TRADING_END_TIME} IST"
        )

    # --------------------------------------------------------
    # VALID BUY SIGNAL
    # --------------------------------------------------------

    elif action.startswith("BUY"):

        current_timestamp = now.timestamp()

        # Same direction cooldown
        if (
            last_action[symbol] == action
            and
            current_timestamp - last_signal_at[symbol]
            < SIGNAL_COOLDOWN_SECONDS
        ):

            result["action"] = "WAIT"
            result["quality"] = "SIGNAL COOLDOWN"

            reasons = [
                "same signal already generated; "
                "waiting for fresh confirmation"
            ]

        # Daily signal limit
        elif (
            len(signal_history[symbol])
            >= MAX_SIGNALS_PER_DAY
        ):

            result["action"] = "NO TRADE"
            result["quality"] = "DAILY SIGNAL LIMIT"

            reasons.append(
                "daily signal limit reached"
            )

        else:

            last_action[symbol] = action
            last_signal_at[symbol] = current_timestamp

            signal_history[symbol].append(
                {
                    "time": now.strftime("%H:%M:%S"),
                    "action": action,
                    "score": result.get("score"),
                    "setup": result.get("setup_name")
                }
            )

    # --------------------------------------------------------
    # FINAL RESPONSE
    # --------------------------------------------------------

    result["reasons"] = reasons

    result["signal_count_today"] = len(
        signal_history[symbol]
    )

    result["signal_history"] = signal_history[
        symbol
    ][-8:]

    return result


# ============================================================
# SHUTDOWN
# ============================================================

@app.on_event("shutdown")
def shutdown():

    try:
        d.stop()
    except Exception:
        pass


# ============================================================
# HOME
# ============================================================

@app.get(
    "/",
    response_class=HTMLResponse
)
def home(request: Request):

    return t.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "scan_seconds": AUTO_SCAN_SECONDS,
            "capital": CAPITAL,
            "risk_pct": RISK_PCT
        }
    )


# ============================================================
# HEALTH
# ============================================================

@app.get("/api/health")
def health():

    status = market_status()

    return {
        "status": "ok",

        "dhan_configured": d.configured(),

        # Safety: no broker order placement
        "auto_trade": False,

        "trading_mode": (
            "PAPER"
            if PAPER_MODE
            else "MANUAL"
        ),

        "websocket": d.websocket_info(),

        "open": status["open"],

        "label": status["label"],

        "time": status["time"],

        "date": status["date"],

        "market_status": status["label"],

        "server_time_ist": status["server_time_ist"],

        "server_date_ist": status["server_date_ist"],

        "timezone": "Asia/Kolkata",

        "entry_window": entry_window_open(),

        "entry_window_start": TRADING_START_TIME,

        "entry_window_end": TRADING_END_TIME
    }


# ============================================================
# SCAN
# ============================================================

@app.get("/api/scan/{symbol}")
def scan(symbol: str):

    symbol = symbol.upper()

    # --------------------------------------------------------
    # SYMBOL VALIDATION
    # --------------------------------------------------------

    if symbol == "NIFTY":

        security_id = NIFTY_SECURITY_ID

    elif symbol == "BANKNIFTY":

        security_id = BANKNIFTY_SECURITY_ID

    else:

        raise HTTPException(
            status_code=400,
            detail="Unsupported symbol. Use NIFTY or BANKNIFTY."
        )

    # --------------------------------------------------------
    # DATA + STRATEGY
    # --------------------------------------------------------

    try:

        # 1. Underlying candles
        candles_data = d.candles(
            security_id
        )

        # 2. Live WebSocket price
        live = d.live_price(
            security_id
        )

        # 3. Current expiry
        expiry = d.expiry(
            security_id
        )

        # 4. Option chain
        chain = d.chain(
            security_id,
            expiry
        )

        # 5. Parse option chain
        spot, option_rows = d.parse(
            chain
        )

        # ----------------------------------------------------
        # LIVE PRICE OVERRIDE
        # ----------------------------------------------------

        if live:

            try:
                live_ltp = float(
                    live.get("ltp", spot)
                )

                if live_ltp > 0:
                    spot = live_ltp

            except Exception:
                pass

        # ----------------------------------------------------
        # FEED DATA
        # ----------------------------------------------------

        candles_data["spot"] = spot

        # ----------------------------------------------------
        # STRATEGY ENGINE
        # ----------------------------------------------------

        result = engine.evaluate(
            candles_data,
            option_rows,
            lot_lookup=d.lot_size,
            capital=CAPITAL,
            risk_pct=RISK_PCT
        )

        # ----------------------------------------------------
        # SAFETY GUARDS
        # ----------------------------------------------------

        result = guarded_result(
            symbol,
            result
        )

        # ----------------------------------------------------
        # SESSION MOVE
        # ----------------------------------------------------

        session_open = candles_data.get(
            "session_open",
            spot
        )

        try:
            session_open = float(
                session_open
            )
        except Exception:
            session_open = float(spot)

        session_move = round(
            spot - session_open,
            2
        )

        session_pct = round(
            (
                session_move
                /
                max(session_open, 1)
            )
            * 100,
            2
        )

        # ----------------------------------------------------
        # FINAL API RESPONSE
        # ----------------------------------------------------

        current = now_ist()

        return {

            "timestamp": current.isoformat(
                timespec="seconds"
            ),

            "server_time_ist": current.strftime(
                "%H:%M:%S"
            ),

            "timezone": "Asia/Kolkata",

            "symbol": symbol,

            "expiry": expiry,

            "spot": round(
                float(spot),
                2
            ),

            "session_open": round(
                session_open,
                2
            ),

            "session_move": session_move,

            "session_pct": session_pct,

            # ------------------------------------------------
            # INDICATORS
            # ------------------------------------------------

            "vwap": round(
                float(candles_data["vwap"]),
                2
            ),

            "ema9": round(
                float(candles_data["ema9"]),
                2
            ),

            "ema21": round(
                float(candles_data["ema21"]),
                2
            ),

            "rsi": round(
                float(
                    candles_data.get(
                        "rsi",
                        50
                    )
                ),
                1
            ),

            "atr": round(
                float(
                    candles_data.get(
                        "atr",
                        0
                    )
                ),
                2
            ),

            "volume_ratio": round(
                float(
                    candles_data.get(
                        "volume_ratio",
                        1
                    )
                ),
                2
            ),

            "short_momentum_pct": round(
                float(
                    candles_data.get(
                        "short_momentum_pct",
                        0
                    )
                ),
                3
            ),

            "candles": candles_data[
                "candles"
            ],

            # ------------------------------------------------
            # LIVE FEED
            # ------------------------------------------------

            "live_feed": live,

            # ------------------------------------------------
            # MODE
            # ------------------------------------------------

            "mode":
                "LIVE WEBSOCKET + REST "
                "CONFIRMATION / MANUAL TRADE",

            "auto_trade": False,

            "trading_mode":
                "PAPER"
                if PAPER_MODE
                else "MANUAL",

            # ------------------------------------------------
            # RISK
            # ------------------------------------------------

            "capital": CAPITAL,

            "risk_pct": RISK_PCT,

            # ------------------------------------------------
            # MARKET TIMING
            # ------------------------------------------------

            **market_status(),

            "entry_window":
                entry_window_open(),

            "entry_window_start":
                TRADING_START_TIME,

            "entry_window_end":
                TRADING_END_TIME,

            # ------------------------------------------------
            # STRATEGY RESULT
            # ------------------------------------------------

            **result
        }

    # --------------------------------------------------------
    # ERROR HANDLING
    # --------------------------------------------------------

    except HTTPException:
        raise

    except Exception as e:

        # Return JSON, never HTML.
        # This also makes frontend debugging easier.
        raise HTTPException(
            status_code=502,
            detail=f"Scan failed for {symbol}: {str(e)}"
        )
