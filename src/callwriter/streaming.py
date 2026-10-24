"""Read-only Upstox V3 market-feed bridge for the dashboard."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _last_price(node: Any) -> float | None:
    if isinstance(node, dict):
        for key in ("ltp", "lastPrice", "last_price"):
            value = _number(node.get(key))
            if value is not None:
                return value
        for value in node.values():
            found = _last_price(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _last_price(value)
            if found is not None:
                return found
    return None


class MarketStreamHub:
    """One background V3 streamer shared by all browser clients.

    The hub subscribes to configured underlyings and any tracked option
    instruments, keeping the latest prices in memory. It has deliberately no
    order or account API.
    """

    def __init__(self, access_token: str, instruments: dict[str, str]):
        self.access_token = access_token
        self.instruments = dict(instruments)
        self._lock = threading.Lock()
        self._latest: dict[str, dict[str, Any]] = {}
        self._streamer = None
        self._error: str | None = None

    def ensure_started(self) -> None:
        with self._lock:
            if self._streamer is not None:
                return
            try:
                import upstox_client

                configuration = upstox_client.Configuration()
                configuration.access_token = self.access_token
                api_client = upstox_client.ApiClient(configuration)
                keys = list(dict.fromkeys(self.instruments.values()))[:100]
                streamer = upstox_client.MarketDataStreamerV3(api_client, keys, "ltpc")
                streamer.on(streamer.Event["MESSAGE"], self._on_message)
                streamer.on(streamer.Event["ERROR"], self._on_error)
                streamer.on(streamer.Event["CLOSE"], self._on_close)
                streamer.auto_reconnect(True, interval=2, retry_count=10)
                streamer.connect()
                self._streamer = streamer
                self._error = None
            except Exception as exc:  # keep REST dashboard usable if feed is unavailable
                self._error = str(exc)

    def update_instruments(self, instruments: dict[str, str]) -> None:
        new_keys = []
        with self._lock:
            known_keys = set(self.instruments.values())
            for label, key in instruments.items():
                if not key:
                    continue
                if key not in known_keys:
                    new_keys.append(key)
                    known_keys.add(key)
                self.instruments[label] = key
            streamer = self._streamer
        if streamer is not None and new_keys:
            try:
                streamer.subscribe(new_keys[:100], "ltpc")
            except Exception as exc:
                with self._lock:
                    self._error = str(exc)

    def _on_error(self, error: Any) -> None:
        with self._lock:
            self._error = str(error)

    def _on_close(self, *_args: Any) -> None:
        with self._lock:
            if self._streamer is not None:
                self._error = "market feed disconnected; reconnecting"

    def _on_message(self, message: dict[str, Any]) -> None:
        feeds = message.get("feeds") if isinstance(message, dict) else None
        if not isinstance(feeds, dict):
            return
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            for key, payload in feeds.items():
                price = _last_price(payload)
                if price is not None:
                    self._latest[key] = {"instrument_key": key, "last_price": price, "timestamp": now, "mode": "websocket"}

    def snapshot(self) -> dict[str, Any]:
        self.ensure_started()
        with self._lock:
            by_symbol = {
                symbol: self._latest[key]
                for symbol, key in self.instruments.items()
                if key in self._latest
            }
            return {"prices": by_symbol, "error": self._error, "connected": self._streamer is not None}

