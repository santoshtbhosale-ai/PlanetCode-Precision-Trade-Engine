from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from dhan_service import DhanService
from strategy import PrecisionEngine
from config import *

from datetime import datetime, time
from zoneinfo import ZoneInfo


# ============================================================
# APP CONFIG
# ============================================================

app = FastAPI(title="PlanetCode Precision Trade Engine V5.5")

t = Jinja2Templates(directory="templates")

d = DhanService()
engine = PrecisionEngine()


# ============================================================
# TIMEZONE
# ============================================================

# Render server can run in UTC.
# NSE market timings are based on India Standard Time.
IST = ZoneInfo("Asia/Kolkata")


def now_ist():
    """Return current India Standard Time."""
    return datetime.now(IST)


# ============================================================
# SIGNAL STATE
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

signal_date = now_ist().date()


# ============================================================
# MARKET STATUS
# ============================================================

def market_status():
    """
    NSE regular market session:
    09:15 AM IST to 03:40 PM IST
    Monday-Friday.

    IMPORTANT:
    Use IST instead of Render/server local time.
    """

    now = now_ist()

    current_time = now.time()

    weekday_open = now.weekday() < 5

    session_open = (
        time(9, 15) <= current_time <= time(15, 40)
    )

    market_open = weekday_open and session_open

    return {
        "open": market_open,
        "label": "MARKET OPEN" if market_open else "MARKET CLOSED",
        "time": now.strftime("%H:%M:%S"),
        "timezone": "Asia/Kolkata",
        "date": now.strftime("%Y-%m-%d")
    }


# ============================================================
# ENTRY WINDOW
# ============================================================

def entry_window_open():
    """
    Fresh trade entry window.

    Default:
    09:20 AM IST
    to
    03:15 PM IST
    """

    now = now_ist().time()

    sh, sm = map(int, TRADING_START_TIME.split(":"))
    eh, em = map(int, TRADING_END_TIME.split(":"))

    return time(sh, sm) <= now <= time(eh, em)


# ============================================================
# DAILY RESET
# ============================================================

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
# SIGNAL GUARD
# ============================================================

def guarded_result(symbol, r):

    reset_daily()

    now = now_ist()

    reasons = list(r.get("reasons", []))

    action = r.get("action", "NO TRADE")

    # --------------------------------------------------------
    # MARKET CLOSED
    # --------------------------------------------------------

    if not market_status()["open"]:

        r["action"] = "NO TRADE"
        r["quality"] = "MARKET CLOSED"

        reasons.append(
            "outside regular NSE market session (09:15-15:40 IST)"
        )

    # --------------------------------------------------------
    # ENTRY WINDOW CLOSED
    # --------------------------------------------------------

    elif not entry_window_open() and action.startswith("BUY"):

        r["action"] = "NO TRADE"
        r["quality"] = "ENTRY WINDOW CLOSED"

        reasons.append(
            f"fresh entries allowed only "
            f"{TRADING_START_TIME}-{TRADING_END_TIME} IST"
        )

    # --------------------------------------------------------
    # VALID BUY SIGNAL
    # --------------------------------------------------------

    elif action.startswith("BUY"):

        # ----------------------------------------------------
        # SIGNAL COOLDOWN
        # ----------------------------------------------------

        if (
            last_action[symbol] == action
            and now.timestamp() - last_signal_at[symbol]
            < SIGNAL_COOLDOWN_SECONDS
        ):

            r["action"] = "WAIT"
            r["quality"] = "SIGNAL COOLDOWN"

            reasons = [
                "same signal already generated; "
                "waiting for fresh confirmation"
            ]

        # ----------------------------------------------------
        # DAILY SIGNAL LIMIT
        # ----------------------------------------------------

        elif len(signal_history[symbol]) >= MAX_SIGNALS_PER_DAY:

            r["action"] = "NO TRADE"
            r["quality"] = "DAILY SIGNAL LIMIT"

            reasons = [
                "daily signal limit reached"
            ]

        # ----------------------------------------------------
        # ACCEPT SIGNAL
        # ----------------------------------------------------

        else:

            last_action[symbol] = action
            last_signal_at[symbol] = now.timestamp()

            signal_history[symbol].append({
                "time": now.strftime("%H:%M:%S"),
                "action": action,
                "score": r.get("score"),
                "setup": r.get("setup_name")
            })

    # --------------------------------------------------------
    # FINAL RESPONSE
    # --------------------------------------------------------

    r["reasons"] = reasons

    r["signal_count_today"] = len(
        signal_history[symbol]
    )

    r["signal_history"] = signal_history[symbol][-8:]

    return r


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
# HOME PAGE
# ============================================================

@app.get("/", response_class=HTMLResponse)
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
# HEALTH CHECK
# ============================================================

@app.get("/api/health")
def health():

    status = market_status()

    return {
        "status": "ok",

        "dhan_configured": d.configured(),

        # Manual trading only
        "auto_trade": False,

        "trading_mode": (
            "PAPER"
            if PAPER_MODE
            else "MANUAL"
        ),

        # Dhan WebSocket status
        "websocket": d.websocket_info(),

        # Market status in IST
        "market_open": status["open"],
        "market_status": status["label"],
        "server_time_ist": status["time"],
        "server_date_ist": status["date"],
        "timezone": "Asia/Kolkata",

        # Trading window
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
    # SECURITY ID
    # --------------------------------------------------------

    if symbol == "NIFTY":

        sid = NIFTY_SECURITY_ID

    elif symbol == "BANKNIFTY":

        sid = BANKNIFTY_SECURITY_ID

    else:

        raise HTTPException(
            status_code=400,
            detail="Unsupported symbol"
        )

    # --------------------------------------------------------
    # MARKET DATA + STRATEGY
    # --------------------------------------------------------

    try:

        # Underlying candles
        f = d.candles(sid)

        # Live WebSocket price
        live = d.live_price(sid)

        # Current expiry
        exp = d.expiry(sid)

        # Option chain
        chain = d.chain(sid, exp)

        # Parse option chain
        spot, rows = d.parse(chain)

        # Prefer fresh WebSocket LTP
        if live:
            spot = live["ltp"]

        f["spot"] = spot

        # ----------------------------------------------------
        # STRATEGY ENGINE
        # ----------------------------------------------------

        r = engine.evaluate(
            f,
            rows,
            lot_lookup=d.lot_size,
            capital=CAPITAL,
            risk_pct=RISK_PCT
        )

        # ----------------------------------------------------
        # SAFETY / MARKET GUARDS
        # ----------------------------------------------------

        r = guarded_result(
            symbol,
            r
        )

        # ----------------------------------------------------
        # SESSION MOVE
        # ----------------------------------------------------

        session_open = f.get(
            "session_open",
            spot
        )

        session_move = round(
            spot - session_open,
            2
        )

        session_pct = round(
            session_move /
            max(session_open, 1) *
            100,
            2
        )

        # ----------------------------------------------------
        # FINAL RESPONSE
        # ----------------------------------------------------

        return {

            # ------------------------------------------------
            # TIME
            # ------------------------------------------------

            "timestamp": now_ist().isoformat(
                timespec="seconds"
            ),

            "server_time_ist": now_ist().strftime(
                "%H:%M:%S"
            ),

            "timezone": "Asia/Kolkata",

            # ------------------------------------------------
            # SYMBOL
            # ------------------------------------------------

            "symbol": symbol,

            "expiry": exp,

            # ------------------------------------------------
            # PRICE
            # ------------------------------------------------

            "spot": round(
                spot,
                2
            ),

            "session_open": round(
                session_open,
                2
            ),

            "session_move": session_move,

            "session_pct": session_pct,

            # ------------------------------------------------
            # TECHNICAL DATA
            # ------------------------------------------------

            "vwap": round(
                f["vwap"],
                2
            ),

            "ema9": round(
                f["ema9"],
                2
            ),

            "ema21": round(
                f["ema21"],
                2
            ),

            "rsi": round(
                f.get("rsi", 50),
                1
            ),

            "atr": round(
                f.get("atr", 0),
                2
            ),

            "volume_ratio": round(
                f.get("volume_ratio", 1),
                2
            ),

            "short_momentum_pct": round(
                f.get(
                    "short_momentum_pct",
                    0
                ),
                3
            ),

            # ------------------------------------------------
            # CANDLES
            # ------------------------------------------------

            "candles": f["candles"],

            # ------------------------------------------------
            # LIVE DATA
            # ------------------------------------------------

            "live_feed": live,

            "feed_mode":
                "LIVE WEBSOCKET + REST CONFIRMATION",

            # ------------------------------------------------
            # TRADING MODE
            # ------------------------------------------------

            "auto_trade": False,

            "trading_mode": (
                "PAPER"
                if PAPER_MODE
                else "MANUAL"
            ),

            # ------------------------------------------------
            # RISK
            # ------------------------------------------------

            "capital": CAPITAL,

            "risk_pct": RISK_PCT,

            # ------------------------------------------------
            # MARKET
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

            **r
        }

    except Exception as e:

        raise HTTPException(
            status_code=502,
            detail=str(e)
        )
