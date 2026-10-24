from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    upstox_access_token: str | None = None
    upstox_api_base: str = "https://api.upstox.com/v2"
    upstox_instruments_url: str = "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"
    callwriter_underlying_keys: dict[str, str] = {}
    callwriter_port: int = 8000
    callwriter_margin_per_lot: float = 0
    model_config = SettingsConfigDict(env_file=PROJECT_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

