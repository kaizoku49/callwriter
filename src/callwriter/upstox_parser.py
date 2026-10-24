from datetime import date
from .models import OptionQuote

def _decimal_iv(value: float | None) -> float | None:
    if value is None:
        return None
    # /option/chain returns examples such as 50.78; Greek/feed APIs may return .5078.
    return value / 100 if value > 3 else value

def option_chain_calls(payload: dict, symbol: str, lot_sizes: dict[str, int] | None = None) -> list[OptionQuote]:
    result = []
    for row in payload.get("data", []):
        call = row.get("call_options") or {}
        market = call.get("market_data") or {}
        greeks = call.get("option_greeks") or {}
        try:
            expiry = date.fromisoformat(row["expiry"])
            spot = float(row["underlying_spot_price"])
            result.append(OptionQuote(
                instrument_key=call["instrument_key"], underlying=symbol,
                strike=float(row["strike_price"]), expiry=expiry, spot=spot,
                ltp=float(market.get("ltp") or 0), bid=float(market.get("bid_price") or 0), ask=float(market.get("ask_price") or 0),
                bid_qty=int(market.get("bid_qty") or 0), ask_qty=int(market.get("ask_qty") or 0),
                oi=int(market.get("oi") or 0), volume=int(market.get("volume") or 0),
                iv=_decimal_iv(greeks.get("iv")), delta=greeks.get("delta"), gamma=greeks.get("gamma"),
                theta=greeks.get("theta"), vega=greeks.get("vega"), lot_size=(lot_sizes or {}).get(call["instrument_key"], 1),
                previous_oi=int(market.get("prev_oi") or 0),
                change_oi=int((market.get("oi") or 0) - (market.get("prev_oi") or 0)),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return result

