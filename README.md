# PlanetCode Precision Trade Engine

Professional NIFTY/BANKNIFTY options decision-support engine.

**Manual trading only. No live order placement is implemented.**

## Features

- DhanHQ V2 WebSocket live underlying LTP
- Dhan Option Chain with caching/rate-limit protection
- Independent CE and PE scoring
- Multiple setups: trend continuation, breakout, opening-range breakout, VWAP bounce/rejection, trend pullback, momentum continuation
- Market regime detection
- Price action, VWAP, EMA, RSI, ATR and volume context
- OI, IV, Delta, volume, premium momentum and bid/ask spread filters
- Smart near-ATM contract selection
- Dynamic setup threshold for strong/normal/choppy regimes
- Signal cooldown and daily signal cap
- Stale-data protection
- Risk-based quantity using instrument-master lot size when available
- Minimum R:R filter
- Professional dashboard
- Signal history

## Installation

```powershell
pip install -r requirements.txt
Copy-Item .env.example .env
```

Put your own Dhan credentials in `.env`. Never commit or share `.env`.

Start:

```powershell
python -m uvicorn main:app --reload
```

Open `http://127.0.0.1:8000`.

## Signal interpretation

- **BUY CE** = bullish setup candidate passing configured filters.
- **BUY PE** = bearish setup candidate passing configured filters.
- **NO TRADE** = conditions are mixed, insufficient, unsafe, stale, outside the entry window, or blocked by a guard.
- **Setup Score is not a win probability.**

The engine intentionally does not force a daily number of trades. Multiple independent setups allow more valid opportunities to be detected without manufacturing signals.

## Dhan data

The app uses DhanHQ V2 WebSocket for live underlying data and Option Chain REST for option-chain confirmation. Option Chain calls are cached because Dhan documents a 3-second unique-request limit.

## Safety

The application does not place, modify or cancel orders. Always verify live contract, price, spread, expiry, quantity and risk in Dhan before manually executing a trade.

## Tests

```powershell
pytest -q tests_strategy.py
```

## Known limitations

- Manual execution means actual realized P&L is not known to the engine unless a future manual-P&L ledger is added.
- Option Chain OI/IV/Greeks are snapshot-style confirmations; they are not tick-history by themselves.
- No profitability or win-rate guarantee is made.


V5.6 behavior change: setup score and trade signal are separated. A high CE/PE setup score is not itself a trade. When the score, regime, option spread and live option price pass entry filters, the engine returns BUY CE/BUY PE. Position sizing is reported separately; if one lot exceeds the configured risk budget, the BUY signal is still shown with an explicit risk warning for manual confirmation.

## V6.0 validation layer
- Historical validation uses Dhan 5-minute underlying candles and tests similar directional setups against a 1 ATR target / 1 ATR stop over the next 12 candles.
- A BUY signal is blocked unless the historical validation sample meets `HISTORICAL_MIN_SAMPLES` and `HISTORICAL_MIN_HIT_RATE` when the gate is enabled.
- News context is headline-risk context only; it cannot create a trade by itself.
- Historical hit-rate is **not** an option-P&L win probability and is not a guarantee of future profit.
