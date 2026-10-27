"""Hard-coded screening universe for the tracker.

The symbols are only a screening universe; the live instrument master remains the
source of truth for instrument keys, available expiries, lot sizes and liquidity.
"""

INDEX_WATCHLIST = ("NIFTY", "BANKNIFTY")

# Top ten Nifty 50 constituents by weight in the latest factsheet reviewed.
# Weights and contract availability must still be refreshed from live metadata.
STOCK_WATCHLIST = (
    "HDFCBANK",
    "ICICIBANK",
    "RELIANCE",
    "BHARTIARTL",
    "LT",
    "INFY",
    "SBIN",
    "AXISBANK",
    "KOTAKBANK",
    "ITC",
)

WATCHLIST = INDEX_WATCHLIST + STOCK_WATCHLIST

