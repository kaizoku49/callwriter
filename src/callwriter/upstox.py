from datetime import date
from urllib.parse import quote
import httpx

class UpstoxMarketData:
    """Market-data-only adapter. It intentionally has no order methods."""
    def __init__(self, access_token: str, base_url: str = "https://api.upstox.com/v2"):
        self.client = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"}, timeout=20)

    def option_chain(self, underlying_key: str, expiry: date) -> dict:
        response = self.client.get("/option/chain", params={"instrument_key": underlying_key, "expiry_date": expiry.isoformat()})
        response.raise_for_status()
        return response.json()

    def option_contracts(self, underlying_key: str, expiry: str | None = None) -> dict:
        params = {"instrument_key": underlying_key}
        if expiry:
            params["expiry_date"] = expiry
        response = self.client.get("/option/contract", params=params)
        response.raise_for_status()
        return response.json()

    def quotes(self, instrument_keys: list[str]) -> dict:
        response = self.client.get("/market-quote/ltp", params={"instrument_key": ",".join(instrument_keys)})
        response.raise_for_status()
        return response.json()

    def full_quotes(self, instrument_keys: list[str]) -> dict:
        response = self.client.get("/market-quote/quotes", params={"instrument_key": ",".join(instrument_keys)})
        response.raise_for_status()
        return response.json()

    def option_greeks(self, instrument_keys: list[str]) -> dict:
        """Return live option Greeks for up to 50 option instrument keys."""
        if not instrument_keys or len(instrument_keys) > 50:
            raise ValueError("Upstox option Greek API supports 1 to 50 instrument keys")
        response = self.client.get(
            "https://api.upstox.com/v3/market-quote/option-greek",
            params={"instrument_key": ",".join(instrument_keys)},
        )
        response.raise_for_status()
        return response.json()

    def market_status(self, exchange: str = "NSE") -> dict:
        response = self.client.get(f"/market/status/{exchange}")
        response.raise_for_status()
        return response.json()

    def market_holidays(self, holiday_date: date | None = None) -> dict:
        path = "/market/holidays"
        if holiday_date:
            path += f"/{holiday_date.isoformat()}"
        response = self.client.get(path)
        response.raise_for_status()
        return response.json()

    def fii(self, data_type: str = "NSE_EQ|CASH", interval: str = "1D") -> dict:
        response = self.client.get("/market/fii", params={"data_type": data_type, "interval": interval})
        response.raise_for_status()
        return response.json()

    def dii(self, data_type: str = "NSE_EQ|CASH", interval: str = "1D") -> dict:
        response = self.client.get("/market/dii", params={"data_type": data_type, "interval": interval})
        response.raise_for_status()
        return response.json()

    def open_interest(self, instrument_key: str, expiry: str, as_of: date | None = None) -> dict:
        params = {"instrument_key": instrument_key, "expiry": expiry}
        if as_of:
            params["date"] = as_of.isoformat()
        response = self.client.get("/market/oi", params=params)
        response.raise_for_status()
        return response.json()

    def change_open_interest(self, instrument_key: str, expiry: str, as_of: date | None = None, interval: int = 1) -> dict:
        params = {"instrument_key": instrument_key, "expiry": expiry, "interval": interval}
        if as_of:
            params["date"] = as_of.isoformat()
        response = self.client.get("/market/change-oi", params=params)
        response.raise_for_status()
        return response.json()

    def max_pain(self, instrument_key: str, expiry: str, as_of: date | None = None, bucket_interval: int = 100) -> dict:
        params = {"instrument_key": instrument_key, "expiry": expiry, "bucket_interval": bucket_interval}
        if as_of:
            params["date"] = as_of.isoformat()
        response = self.client.get("/market/max-pain", params=params)
        response.raise_for_status()
        return response.json()

    def put_call_ratio(self, instrument_key: str, expiry: str, as_of: date | None = None, bucket_interval: int = 100) -> dict:
        params = {"instrument_key": instrument_key, "expiry": expiry, "bucket_interval": bucket_interval}
        if as_of:
            params["date"] = as_of.isoformat()
        response = self.client.get("/market/pcr", params=params)
        response.raise_for_status()
        return response.json()

    def historical_closes(self, instrument_key: str, from_date: date, to_date: date) -> list[float]:
        path_key = quote(instrument_key, safe="")
        response = self.client.get(f"https://api.upstox.com/v3/historical-candle/{path_key}/days/1/{to_date.isoformat()}/{from_date.isoformat()}")
        response.raise_for_status()
        candles = response.json().get("data", {}).get("candles", [])
        candles = sorted(candles, key=lambda candle: candle[0])
        return [float(candle[4]) for candle in candles if len(candle) > 4 and float(candle[4]) > 0]

    def intraday_candles(self, instrument_key: str, interval_minutes: int = 5) -> dict:
        """Return current-session OHLC candles from the read-only V3 history API."""
        if not 1 <= interval_minutes <= 300:
            raise ValueError("interval_minutes must be between 1 and 300")
        path_key = quote(instrument_key, safe="")
        response = self.client.get(
            f"https://api.upstox.com/v3/historical-candle/intraday/{path_key}/minutes/{interval_minutes}"
        )
        response.raise_for_status()
        return response.json()


