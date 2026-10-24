from dataclasses import dataclass
from datetime import date

@dataclass(frozen=True)
class OptionQuote:
    instrument_key: str
    underlying: str
    strike: float
    expiry: date
    spot: float
    ltp: float
    bid: float
    ask: float
    bid_qty: int = 0
    ask_qty: int = 0
    oi: int = 0
    volume: int = 0
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    lot_size: int = 1
    previous_oi: int = 0
    change_oi: int = 0

@dataclass(frozen=True)
class Candidate:
    quote: OptionQuote
    dte: float
    historical_vol: float
    probability_otm: float
    expected_move: float
    expected_upper_range: float
    volatility_stop_loss: float
    stop_loss_breached: bool
    iv_hv_ratio: float
    iv_skew: float | None
    term_structure_ratio: float | None
    premium_yield: float
    score: float
    warnings: tuple[str, ...]

