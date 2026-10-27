# CallWriter Tracker

Read-only tracker for screening near-expiry, out-of-the-money NSE call options using Upstox market data. It does **not** place orders and has no order API integration.

## Design

- NIFTY and BANKNIFTY are screened against the nearest future contract with `weekly=true`.
- Stock options are screened against the nearest future contract with `weekly=false` (monthly expiry).
- The instrument master is the source of truth for expiry, instrument key and lot size; expiry symbols are never constructed manually.
- Candidate calls first use the Varsity method: calculate the mean and standard deviation of log returns, project the upper price range until expiry, and require the strike to be at or above that upper range. The default is one standard deviation; the nearest available strike is preferred, subject to premium and liquidity filters.
- The same upper volatility range is exposed as the underlying stop-loss/invalidation level for a written call. The tracker flags a breached level; it does not translate it into an unreliable fixed option-premium stop.
- The dashboard reports NIFTY 50/200-day trend, watchlist breadth, volatility stress, and India VIX as market context. The broad NIFTY trend/breadth gate is informational and does not block scanning. The independent VIX safety filter warns when VIX is elevated and blocks candidates only at extreme VIX levels.
- A top-level market-sentiment card labels the current context as bullish, bearish, neutral, or unavailable. It is informational only and does not place trades or override the scanner.
- The web tracker displays the selected underlying's OHLC chart using 5-minute or 15-minute candles; hovering the chart shows a crosshair, cursor price, timestamp and OHLC values. Chart data uses Upstox's read-only intraday candle API.
- The dashboard also shows the selected underlying's live price, net change and percentage change, refreshing every 15 seconds through the read-only market quote API.
- The dashboard also opens a read-only Upstox V3 WebSocket for the configured underlyings. It keeps the latest in-memory prices in the live-price card and automatically falls back to the REST quote refresh if the stream is unavailable.
- Tracked hypothetical calls are lot-based: each record stores an explicit lot count and shows P/L per lot, total P/L, and estimated effective expense. The combined tracked allocation must remain below the fixed ₹10 lakh effective-expense cap. If an assumed margin per lot is not configured, the conservative underlying-notional fallback is used; this is not a broker-margin calculation.
- Tracked calls and paper events persist in a local SQLite database. The dashboard includes live tracked-option prices through the read-only market stream, expiry countdowns, option-chain OI bars, scan explanations, data-quality status, paper history, and CSV exports.
- Candidate liquidity requires a two-sided quote, minimum volume/OI/quote quantity, and a maximum bid-ask spread. The scanner also compares IV with historical volatility, measures same-expiry strike skew, and measures front-versus-next-expiry IV when multiple expiries are supplied.
- Monitoring alerts track the underlying volatility stop, delta, option-premium multiple, gamma, and spread widening for a hypothetical tracked call. These alerts do not represent an open broker position and cannot place trades.
- Read-only strategy profiles include the original naked call write, a covered call requiring the underlying, and a defined-risk bear call spread. The spread helper reports credit, maximum profit, maximum loss, and risk/reward; no profile can place an order.
- Delta, IV, gamma, theta and vega are secondary risk checks. Delta is not the primary strike-selection rule.
- Historical volatility is annualized from log returns. If Upstox supplies IV/Greeks they should be preferred for market-risk context; the range calculation remains based on historical volatility to stay faithful to the Varsity method.
- Fundamental strength is deliberately a configuration/input concern, not inferred from option prices. Add an approved watchlist upstream before screening stock options.
- Fundamentals, expired instruments, news, and all trading/order/account APIs are intentionally excluded. The app does not fetch financial fundamentals.

The initial hard-coded universe is `NIFTY`, `BANKNIFTY`, plus the current top-ten Nifty 50 constituents by weightage: `HDFCBANK`, `ICICIBANK`, `RELIANCE`, `BHARTIARTL`, `LT`, `INFY`, `SBIN`, `AXISBANK`, `KOTAKBANK`, and `ITC`. See `src/callwriter/watchlist.py`. This is not a current investment recommendation; the tracker should still validate that each symbol has an active, liquid option contract in the Upstox instrument master.

## Safety

The adapter exposes only market-data calls. There is no `place_order`, `modify_order`, GTT, portfolio or order-management method. Treat every candidate as a research alert: short calls have theoretically unlimited loss, and near expiry gamma, liquidity, gaps, corporate actions and physical settlement can dominate the model.

## Run

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e .
cp .env.example .env  # fill a read-only market-data token
callwriter --underlying-key 'NSE_INDEX|...' --expiry 2026-10-29
```

## Web tracker

```bash
callwriter-web
```

Open `http://127.0.0.1:8000`. Without `UPSTOX_ACCESS_TOKEN`, the page runs in clearly labelled demo mode. For project-level configuration, copy `.env.example` to `.env` and set `UPSTOX_ACCESS_TOKEN`; `.env` is ignored by Git and loaded when the dashboard starts. NIFTY, BANKNIFTY and the ten configured stocks use built-in Upstox instrument mappings; `CALLWRITER_UNDERLYING_KEYS` can override them in `.env`. The combined effective-expense cap is fixed at ₹10 lakh, while `CALLWRITER_MARGIN_PER_LOT` optionally supplies the assumed expense per lot. “Track” creates a persistent hypothetical record only. It is not an Upstox position and cannot place trades.

Upstox documents instrument keys, expiries and lot sizes in its instrument master; use those values rather than constructing symbols manually.

