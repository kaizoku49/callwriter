import asyncio
import csv
import io
import json
import uuid
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .config import Settings
from .models import OptionQuote
from .monitoring import monitor_short_call
from .greeks import annualized_historical_vol, mean_log_return
from .market_filter import evaluate_market_filter
from .strategy import StrategyConfig, rank_calls
from .streaming import MarketStreamHub
from .storage import delete_tracked as delete_tracked_record
from .storage import history, init_db, load_tracked, record_event, save_tracked
from .upstox import UpstoxMarketData
from .upstox_parser import option_chain_calls
from .watchlist import WATCHLIST

app = FastAPI(title="CallWriter Tracker", docs_url="/api/docs")
settings = Settings()
data_client = None
stream_hub = None
tracked: dict[str, dict] = {}
runtime_underlying_keys: dict[str, str] = {}
MAX_EFFECTIVE_EXPENSE = 1_000_000.0
DEFAULT_UNDERLYING_KEYS = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "HDFCBANK": "NSE_EQ|INE040A01034",
    "ICICIBANK": "NSE_EQ|INE090A01021",
    "RELIANCE": "NSE_EQ|INE002A01018",
    "BHARTIARTL": "NSE_EQ|INE397D01024",
    "LT": "NSE_EQ|INE018A01030",
    "INFY": "NSE_EQ|INE009A01021",
    "SBIN": "NSE_EQ|INE062A01020",
    "AXISBANK": "NSE_EQ|INE238A01034",
    "KOTAKBANK": "NSE_EQ|INE237A01036",
    "ITC": "NSE_EQ|INE154A01025",
}
init_db()
tracked.update(load_tracked())

class ScanRequest(BaseModel):
    symbol: str = "NIFTY"
    underlying_key: str | None = None
    expiry: str | None = None

class ChartRequest(BaseModel):
    symbol: str = "NIFTY"
    underlying_key: str | None = None
    timeframe: str = "5m"

class PriceRequest(BaseModel):
    symbol: str = "NIFTY"
    underlying_key: str | None = None

class AnalyticsRequest(BaseModel):
    symbol: str = "NIFTY"
    underlying_key: str | None = None
    expiry: str | None = None
    date: str | None = None

class TrackRequest(BaseModel):
    candidate: dict
    entry_premium: float
    entry_spot: float
    lots: int = Field(default=1, ge=1, le=1000)

def _live() -> bool:
    return bool(settings.upstox_access_token)

def _mapping() -> dict[str, str]:
    mapping = dict(DEFAULT_UNDERLYING_KEYS)
    mapping.update(settings.callwriter_underlying_keys)
    mapping.update(runtime_underlying_keys)
    return mapping

def _tracked_stream_instruments() -> dict[str, str]:
    return {
        f"tracked:{item_id}": (item.get("quote") or {}).get("instrument_key", "")
        for item_id, item in tracked.items()
        if (item.get("quote") or {}).get("instrument_key")
    }

def _effective_expense_per_lot(quote: dict, entry_spot: float | None = None) -> float:
    if settings.callwriter_margin_per_lot > 0:
        return float(settings.callwriter_margin_per_lot)
    spot = float(entry_spot or quote.get("spot") or 0)
    lot_size = max(1, int(quote.get("lot_size") or 1))
    return spot * lot_size

def _tracked_effective_expense(item: dict) -> float:
    stored = item.get("effective_expense")
    if stored is not None:
        return float(stored)
    quote = item.get("quote") or {}
    lots = max(1, int(item.get("lots") or 1))
    return _effective_expense_per_lot(quote, item.get("entry_spot")) * lots

def _demo_quotes(symbol: str) -> list[OptionQuote]:
    expiry = date.today()
    while expiry.weekday() >= 5:
        expiry = expiry.replace(day=expiry.day + 1)
    return [OptionQuote(f"DEMO|{symbol}|{strike}", symbol, strike, expiry, 100, 1.0, .95, 1.05, 100, 100, 1000, 10000, .20, .12, .001, -0.1, .5) for strike in (103, 105, 108, 110)]

def _demo_candles() -> list[dict]:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    candles = []
    price = 100.0
    for index in range(78):
        timestamp = now - timedelta(minutes=5 * (77 - index))
        open_price = price
        close_price = open_price + (0.18 if index % 5 in (1, 2, 3) else -0.08)
        high_price = max(open_price, close_price) + 0.12
        low_price = min(open_price, close_price) - 0.10
        candles.append({"timestamp": timestamp.isoformat(), "open": round(open_price, 2), "high": round(high_price, 2), "low": round(low_price, 2), "close": round(close_price, 2), "volume": 0})
        price = close_price
    return candles

def _format_candles(payload: dict) -> list[dict]:
    result = []
    for candle in payload.get("data", {}).get("candles", []):
        if len(candle) < 5:
            continue
        result.append({
            "timestamp": candle[0],
            "open": float(candle[1]),
            "high": float(candle[2]),
            "low": float(candle[3]),
            "close": float(candle[4]),
            "volume": float(candle[5]) if len(candle) > 5 else 0,
        })
    return sorted(result, key=lambda candle: candle["timestamp"])

def _underlying_key(symbol: str, supplied: str | None) -> str | None:
    if supplied:
        return supplied
    mapping = _mapping()
    return mapping.get(symbol)

def _client() -> UpstoxMarketData:
    global data_client
    if data_client is None:
        token = settings.upstox_access_token
        if not token:
            raise HTTPException(400, "No Upstox access token configured")
        data_client = UpstoxMarketData(token, settings.upstox_api_base)
    return data_client

def _resolve_expiry(client: UpstoxMarketData, symbol: str, key: str, supplied: str | None = None) -> str:
    if supplied:
        return supplied
    expiry_kind = "current_week" if symbol == "NIFTY" else "current_month"
    contracts = client.option_contracts(key).get("data", [])
    weekly = symbol == "NIFTY"
    active = sorted({
        item.get("expiry")
        for item in contracts
        if item.get("expiry") and bool(item.get("weekly")) is weekly
    })
    if not active:
        raise HTTPException(502, f"No active {expiry_kind} contracts returned for {symbol}")
    today = date.today().isoformat()
    upcoming = [expiry for expiry in active if expiry >= today]
    if not upcoming:
        raise HTTPException(502, f"No upcoming {expiry_kind} contracts returned for {symbol}")
    return upcoming[0]

def _lot_sizes(client: UpstoxMarketData, key: str, expiry: str) -> dict[str, int]:
    try:
        rows = client.option_contracts(key, expiry).get("data", [])
        return {
            row["instrument_key"]: int(row.get("lot_size") or row.get("minimum_lot") or 1)
            for row in rows
            if row.get("instrument_key")
        }
    except Exception:
        return {}

def _safe_call(label: str, callback) -> dict:
    try:
        return {"data": callback(), "error": None}
    except Exception as exc:
        return {"data": None, "error": f"{label}: {exc}"}

def _option_chain_summary(payload: dict, calls: list[OptionQuote]) -> dict:
    rows = payload.get("data") or []
    spot = None
    pcr = None
    total_call_oi = 0
    total_put_oi = 0
    puts = []
    for row in rows:
        if spot is None and row.get("underlying_spot_price") is not None:
            spot = float(row["underlying_spot_price"])
        if pcr is None and row.get("pcr") is not None:
            pcr = float(row["pcr"])
        call = row.get("call_options") or {}
        put = row.get("put_options") or {}
        call_market = call.get("market_data") or {}
        put_market = put.get("market_data") or {}
        total_call_oi += int(call_market.get("oi") or 0)
        total_put_oi += int(put_market.get("oi") or 0)
        if put.get("instrument_key"):
            puts.append({
                "instrument_key": put.get("instrument_key"),
                "strike": row.get("strike_price"),
                "oi": put_market.get("oi", 0),
                "previous_oi": put_market.get("prev_oi", 0),
                "change_oi": int((put_market.get("oi") or 0) - (put_market.get("prev_oi") or 0)),
                "ltp": put_market.get("ltp", 0),
                "bid": put_market.get("bid_price", 0),
                "ask": put_market.get("ask_price", 0),
            })
    if pcr is None and total_call_oi:
        pcr = total_put_oi / total_call_oi
    return {
        "spot": spot,
        "pcr": pcr,
        "total_call_oi": total_call_oi,
        "total_put_oi": total_put_oi,
        "calls": [asdict(q) for q in calls],
        "puts": puts,
    }

def _demo_analytics(symbol: str) -> dict:
    return {
        "mode": "demo", "symbol": symbol, "fetched_at": datetime.now(timezone.utc).isoformat(),
        "market_status": {"data": {"status": "demo"}, "error": None},
        "holiday": {"data": None, "error": "Demo mode"},
        "fii": {"data": None, "error": "Demo mode"}, "dii": {"data": None, "error": "Demo mode"},
        "option_greeks": {"data": None, "error": "Demo mode"},
        "oi": {"data": None, "error": "Demo mode"}, "change_oi": {"data": None, "error": "Demo mode"},
        "max_pain": {"data": None, "error": "Demo mode"}, "pcr": {"data": None, "error": "Demo mode"},
        "option_chain": {"spot": 100.0, "pcr": 0.8, "total_call_oi": 1000, "total_put_oi": 800, "calls": [], "puts": []},
    }

def _analytics(req: AnalyticsRequest) -> dict:
    if not _live():
        return _demo_analytics(req.symbol)
    client = _client()
    key = _underlying_key(req.symbol, req.underlying_key)
    if not key:
        raise HTTPException(400, f"No underlying key configured for {req.symbol}")
    as_of = date.fromisoformat(req.date) if req.date else date.today()
    expiry = None
    expiry_error = None
    try:
        expiry = _resolve_expiry(client, req.symbol, key, req.expiry)
    except Exception as exc:
        expiry_error = f"active expiry: {exc}"
    chain_payload = _safe_call("option chain", lambda: client.option_chain(key, date.fromisoformat(expiry))) if expiry else {"data": None, "error": expiry_error}
    chain_calls: list[OptionQuote] = []
    if chain_payload["data"]:
        chain_calls = option_chain_calls(chain_payload["data"], req.symbol, _lot_sizes(client, key, expiry))
    option_keys = [q.instrument_key for q in chain_calls[:50]]
    return {
        "mode": "live", "symbol": req.symbol, "underlying_key": key, "expiry": expiry, "as_of": as_of.isoformat(), "fetched_at": datetime.now(timezone.utc).isoformat(),
        "market_status": _safe_call("market status", lambda: client.market_status("NSE")),
        "holiday": _safe_call("market holidays", lambda: client.market_holidays(as_of)),
        "fii": _safe_call("FII", lambda: client.fii()),
        "dii": _safe_call("DII", lambda: client.dii()),
        "option_greeks": _safe_call("option Greeks", lambda: client.option_greeks(option_keys)) if option_keys else {"data": None, "error": "No option keys returned"},
        "oi": _safe_call("open interest", lambda: client.open_interest(key, expiry, as_of)) if expiry else {"data": None, "error": expiry_error},
        "change_oi": _safe_call("change in open interest", lambda: client.change_open_interest(key, expiry, as_of)) if expiry else {"data": None, "error": expiry_error},
        "max_pain": _safe_call("max pain", lambda: client.max_pain(key, expiry, as_of)) if expiry else {"data": None, "error": expiry_error},
        "pcr": _safe_call("PCR", lambda: client.put_call_ratio(key, expiry, as_of)) if expiry else {"data": None, "error": expiry_error},
        "option_chain": _option_chain_summary(chain_payload["data"], chain_calls) if chain_payload["data"] else {"error": chain_payload["error"]},
    }

def _live_context() -> tuple[dict, object]:
    mapping = _mapping()
    end = date.today()
    start = end - timedelta(days=500)
    nifty_key = mapping.get("NIFTY")
    if not nifty_key:
        return {}, None
    try:
        nifty_closes = data_client.historical_closes(nifty_key, start, end)
        stock_closes = {}
        for symbol in WATCHLIST[1:]:
            key = mapping.get(symbol)
            if key:
                stock_closes[symbol] = data_client.historical_closes(key, start, end)
        vix_closes = data_client.historical_closes("NSE_INDEX|India VIX", start, end)
        market = evaluate_market_filter(nifty_closes, stock_closes, vix_closes)
        return {"nifty_closes": nifty_closes}, market
    except Exception:
        return {}, None

def _sentiment_label(market) -> str:
    if market is None:
        return "unknown"
    if market.vix_extreme or (not market.nifty_above_sma50 and not market.nifty_above_sma200 and market.breadth_above_sma50 < 0.50):
        return "bearish"
    if market.nifty_above_sma50 and market.nifty_above_sma200 and market.breadth_above_sma50 >= 0.50 and not market.volatility_spike and not market.vix_elevated:
        return "bullish"
    return "neutral"

def _scan(req: ScanRequest) -> tuple[list[OptionQuote], str, dict]:
    if not _live():
        return _demo_quotes(req.symbol), "demo", {}
    client = _client()
    key = _underlying_key(req.symbol, req.underlying_key)
    if not key:
        raise HTTPException(400, f"No underlying key configured for {req.symbol}")
    expiry = _resolve_expiry(client, req.symbol, key, req.expiry)
    quotes = option_chain_calls(client.option_chain(key, date.fromisoformat(expiry)), req.symbol, _lot_sizes(client, key, expiry))
    context, market = _live_context()
    closes = client.historical_closes(key, date.today() - timedelta(days=500), date.today())
    context["historical_vol"] = annualized_historical_vol(closes) if len(closes) >= 3 else .20
    context["daily_mean_log_return"] = mean_log_return(closes) if len(closes) >= 2 else 0.0
    context["market_filter"] = market
    context["expiry"] = expiry
    context["fetched_at"] = datetime.now(timezone.utc).isoformat()
    return quotes, "live", context

@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")

@app.get("/api/health")
def health():
    return {"status": "ok", "mode": "live" if _live() else "demo", "token_configured": _live(), "tracked_count": len(tracked), "max_effective_expense": MAX_EFFECTIVE_EXPENSE, "margin_per_lot": settings.callwriter_margin_per_lot}

@app.get("/api/watchlist")
def watchlist():
    return {"symbols": WATCHLIST}

@app.get("/api/config")
def public_config():
    return {"max_effective_expense": MAX_EFFECTIVE_EXPENSE, "margin_per_lot": settings.callwriter_margin_per_lot, "read_only": True}

@app.get("/api/sentiment")
def sentiment():
    if not _live():
        return {"mode": "demo", "sentiment": "neutral", "label": "Demo / neutral", "reasons": ["Configure a live Upstox token for market sentiment."], "fetched_at": datetime.now(timezone.utc).isoformat()}
    _client()
    _, market, _ = _live_context()
    if market is None:
        return {"mode": "live", "sentiment": "unknown", "label": "Unavailable", "reasons": ["Market context could not be fetched."], "fetched_at": datetime.now(timezone.utc).isoformat()}
    label = _sentiment_label(market)
    return {"mode": "live", "sentiment": label, "label": label.capitalize(), "reasons": list(market.reasons), "market_filter": asdict(market), "fetched_at": datetime.now(timezone.utc).isoformat()}

@app.post("/api/chart")
def chart(req: ChartRequest):
    if req.timeframe not in {"5m", "15m"}:
        raise HTTPException(400, "timeframe must be one of: 5m, 15m")
    if not _live():
        return {"mode": "demo", "symbol": req.symbol, "timeframe": req.timeframe, "candles": _demo_candles(), "message": "Demo chart data; configure the project .env for live candles."}
    global data_client
    if data_client is None:
        token = settings.upstox_access_token
        if not token:
            raise HTTPException(400, "No Upstox access token configured")
        data_client = UpstoxMarketData(token, settings.upstox_api_base)
    key = _underlying_key(req.symbol, req.underlying_key)
    if not key:
        raise HTTPException(400, f"No underlying key configured for {req.symbol}")
    interval = 5 if req.timeframe == "5m" else 15
    payload = data_client.intraday_candles(key, interval)
    return {"mode": "live", "symbol": req.symbol, "timeframe": req.timeframe, "candles": _format_candles(payload)}

@app.post("/api/price")
def price(req: PriceRequest):
    if not _live():
        return {"mode": "demo", "symbol": req.symbol, "last_price": 100.0, "net_change": 0.0, "change_percent": 0.0, "timestamp": datetime.now(timezone.utc).isoformat()}
    client = _client()
    key = _underlying_key(req.symbol, req.underlying_key)
    if not key:
        raise HTTPException(400, f"No underlying key configured for {req.symbol}")
    payload = client.full_quotes([key]).get("data", {})
    quote = payload.get(key) or (next(iter(payload.values())) if payload else {})
    last_price = float(quote.get("last_price", 0))
    net_change = float(quote.get("net_change", 0))
    previous_close = last_price - net_change
    change_percent = (net_change / previous_close * 100) if previous_close else 0.0
    return {"mode": "live", "symbol": req.symbol, "last_price": last_price, "net_change": net_change, "change_percent": change_percent, "timestamp": quote.get("timestamp") or quote.get("last_trade_time")}

@app.post("/api/analytics")
def analytics(req: AnalyticsRequest):
    return _analytics(req)

@app.websocket("/api/ws/market")
async def market_stream(websocket: WebSocket):
    await websocket.accept()
    global stream_hub
    if not _live():
        try:
            while True:
                await websocket.send_json({"type": "snapshot", "mode": "demo", "connected": False, "prices": {}, "error": "UPSTOX_ACCESS_TOKEN is not configured"})
                await asyncio.sleep(2)
        except WebSocketDisconnect:
            return
    if stream_hub is None:
        stream_hub = MarketStreamHub(settings.upstox_access_token, _mapping())
    stream_hub.update_instruments(_tracked_stream_instruments())
    try:
        while True:
            snapshot = stream_hub.snapshot()
            await websocket.send_json({"type": "snapshot", "mode": "live", **snapshot})
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return

@app.post("/api/scan")
def scan(req: ScanRequest):
    quotes, mode, context = _scan(req)
    if mode == "demo":
        # Demo mode displays raw quotes so the UI remains testable without pretending
        # that synthetic data is a strategy recommendation.
        result = {"mode": mode, "symbol": req.symbol, "candidates": [asdict(q) for q in quotes], "message": "Demo data only; configure UPSTOX_ACCESS_TOKEN for live ranking."}
        record_event("scan", req.symbol, details={"candidate_count": len(quotes), "mode": mode})
        return result
    candidates = rank_calls(quotes, context["historical_vol"], date.today(), daily_mean_log_return=context["daily_mean_log_return"], market_filter=context.get("market_filter"))
    no_candidate_reasons: list[str] = []
    if not candidates:
        expiry = context.get("expiry")
        if expiry:
            dte = (date.fromisoformat(expiry) - date.today()).days
            if dte > StrategyConfig().max_dte:
                no_candidate_reasons.append(f"Expiry is {dte} calendar days away; this scanner accepts at most {int(StrategyConfig().max_dte)} days.")
        market_filter = context.get("market_filter")
        if market_filter and market_filter.vix_extreme:
            no_candidate_reasons.append("Extreme India VIX blocks new candidates for safety.")
        if not no_candidate_reasons:
            no_candidate_reasons.append("No calls passed the Varsity range, delta, IV/HV, liquidity, spread and premium filters.")
    result = {"mode": mode, "symbol": req.symbol, "expiry": context.get("expiry"), "fetched_at": context.get("fetched_at"), "historical_vol": context["historical_vol"], "market_filter": asdict(context["market_filter"]) if context.get("market_filter") else None, "candidates": [asdict(c) for c in candidates], "no_candidate_reasons": no_candidate_reasons, "selection_rule": "Varsity upper-range strike plus delta, IV/HV, liquidity and independent VIX safety filter; NIFTY trend/breadth gate is informational only"}
    record_event("scan", req.symbol, details={"candidate_count": len(candidates), "expiry": context.get("expiry"), "mode": mode})
    return result

@app.get("/api/tracked")
def get_tracked():
    return {"items": list(tracked.values())}

@app.post("/api/tracked/refresh")
def refresh_tracked():
    if not tracked:
        return {"updated": 0, "items": []}
    updated = 0
    if _live():
        for item in tracked.values():
            symbol = (item.get("quote") or {}).get("underlying")
            if not symbol:
                continue
            try:
                quotes, _, _ = _scan(ScanRequest(symbol=symbol))
                key = (item.get("quote") or {}).get("instrument_key")
                current = next((q for q in quotes if q.instrument_key == key), None)
                if current is None:
                    continue
                stop = item.get("volatility_stop_loss", item["entry_spot"] * 1.05)
                alert = monitor_short_call(current, item["entry_spot"], item["entry_premium"], stop)
                item["quote"] = asdict(current)
                item["alerts"] = list(alert.alerts)
                item["last_update"] = date.today().isoformat()
                save_tracked(item)
                record_event("refresh", symbol, key, {"ltp": current.ltp, "alerts": item["alerts"]})
                updated += 1
            except Exception as exc:
                item["alerts"] = [f"refresh unavailable: {exc}"]
    return {"updated": updated, "items": list(tracked.values())}

@app.post("/api/tracked")
def add_tracked(req: TrackRequest):
    item = dict(req.candidate)
    quote = item.get("quote") or {}
    effective_expense = _effective_expense_per_lot(quote, req.entry_spot) * req.lots
    combined_expense = sum(_tracked_effective_expense(existing) for existing in tracked.values()) + effective_expense
    if combined_expense >= MAX_EFFECTIVE_EXPENSE:
        raise HTTPException(400, f"This would take total tracked effective expense to ₹{combined_expense:,.0f}; it must remain below ₹{MAX_EFFECTIVE_EXPENSE:,.0f}")
    item.update({"id": str(uuid.uuid4()), "entry_premium": req.entry_premium, "entry_spot": req.entry_spot, "lots": req.lots, "effective_expense": effective_expense, "status": "tracked"})
    tracked[item["id"]] = item
    save_tracked(item)
    record_event("track", quote.get("underlying"), quote.get("instrument_key"), {"strike": quote.get("strike"), "entry_premium": req.entry_premium, "lots": req.lots, "effective_expense": effective_expense})
    if stream_hub is not None:
        stream_hub.update_instruments(_tracked_stream_instruments())
    return item

@app.delete("/api/tracked/{item_id}")
def delete_tracked(item_id: str):
    if item_id not in tracked:
        raise HTTPException(404, "Tracked item not found")
    item = tracked.pop(item_id)
    delete_tracked_record(item_id)
    record_event("remove", (item.get("quote") or {}).get("underlying"), (item.get("quote") or {}).get("instrument_key"), {"strike": (item.get("quote") or {}).get("strike")})
    return item

@app.get("/api/history")
def get_history(limit: int = 200):
    return {"items": history(limit)}

def _csv_response(filename: str, rows: list[dict]) -> StreamingResponse:
    buffer = io.StringIO()
    if rows:
        fields = list(rows[0].keys())
        writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

@app.get("/api/export/tracked.csv")
def export_tracked():
    rows = []
    for item in tracked.values():
        quote = item.get("quote") or {}
        rows.append({"id": item.get("id"), "symbol": quote.get("underlying"), "instrument_key": quote.get("instrument_key"), "strike": quote.get("strike"), "expiry": quote.get("expiry"), "lots": item.get("lots", 1), "effective_expense": item.get("effective_expense"), "entry_premium": item.get("entry_premium"), "current_premium": quote.get("ltp"), "entry_spot": item.get("entry_spot"), "status": item.get("status"), "alerts": "; ".join(item.get("alerts") or [])})
    return _csv_response("callwriter-tracked.csv", rows)

@app.get("/api/export/history.csv")
def export_history():
    rows = []
    for item in history(1000):
        row = dict(item)
        row["details"] = json.dumps(row["details"], default=str)
        rows.append(row)
    return _csv_response("callwriter-history.csv", rows)

def main():
    import uvicorn
    uvicorn.run("callwriter.web:app", host="127.0.0.1", port=settings.callwriter_port, reload=False)

