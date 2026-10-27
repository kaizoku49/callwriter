from datetime import date, datetime, timezone

def expiry_date(instrument: dict) -> date:
    """Convert Upstox's expiry milliseconds to an exchange-calendar date."""
    value = instrument.get("expiry")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date()
    return date.fromisoformat(str(value)[:10])

def select_expiry_instruments(instruments: list[dict], symbol: str, as_of: date | None = None) -> list[dict]:
    """Return the nearest eligible expiry chain for a watchlist symbol.

    NIFTY and BANKNIFTY use weekly contracts. Stock options use monthly contracts, represented
    by weekly=False in the Upstox instrument master.
    """
    as_of = as_of or date.today()
    wanted_weekly = symbol in {"NIFTY", "BANKNIFTY"}
    matches = [
        item for item in instruments
        if item.get("segment") == "NSE_FO"
        and item.get("underlying_symbol") == symbol
        and item.get("instrument_type") == "CE"
        and bool(item.get("weekly", False)) == wanted_weekly
        and expiry_date(item) >= as_of
    ]
    if not matches:
        return []
    nearest = min(expiry_date(item) for item in matches)
    return [item for item in matches if expiry_date(item) == nearest]

