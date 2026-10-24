import argparse, json
from datetime import date
from .config import Settings
from .upstox import UpstoxMarketData

def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Upstox call-writing tracker")
    parser.add_argument("--underlying-key", required=True, help="e.g. NSE_INDEX|Nifty 50 instrument key")
    parser.add_argument("--expiry", help="YYYY-MM-DD; omit to select the correct weekly/monthly expiry from metadata")
    args = parser.parse_args()
    settings = Settings()
    data = UpstoxMarketData(settings.upstox_access_token, settings.upstox_api_base)
    if not args.expiry:
        raise SystemExit("Automatic expiry selection requires loading the Upstox instrument master; use --expiry for a direct chain lookup.")
    print(json.dumps(data.option_chain(args.underlying_key, date.fromisoformat(args.expiry)), indent=2))

