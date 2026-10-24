from dataclasses import dataclass
from enum import Enum
from .models import OptionQuote

class StrategyType(str, Enum):
    CALL_WRITE = "call_write"
    COVERED_CALL = "covered_call"
    BEAR_CALL_SPREAD = "bear_call_spread"

@dataclass(frozen=True)
class StrategyProfile:
    name: StrategyType
    requires_underlying: bool
    defined_risk: bool
    description: str

PROFILES = {
    StrategyType.CALL_WRITE: StrategyProfile(StrategyType.CALL_WRITE, False, False, "Sell an OTM call; unlimited upside risk."),
    StrategyType.COVERED_CALL: StrategyProfile(StrategyType.COVERED_CALL, True, False, "Hold the underlying and sell an OTM call; upside is capped."),
    StrategyType.BEAR_CALL_SPREAD: StrategyProfile(StrategyType.BEAR_CALL_SPREAD, False, True, "Sell the selected call and buy a higher-strike call to cap risk."),
}

@dataclass(frozen=True)
class SpreadCandidate:
    short_call: OptionQuote
    long_call: OptionQuote
    credit: float
    max_profit: float
    max_loss: float
    risk_reward: float

def build_bear_call_spread(short_call: OptionQuote, long_call: OptionQuote) -> SpreadCandidate:
    if long_call.strike <= short_call.strike:
        raise ValueError("Long call strike must be above the short call strike")
    credit = max(0.0, short_call.bid - long_call.ask)
    width = long_call.strike - short_call.strike
    max_loss = max(0.0, width - credit)
    return SpreadCandidate(short_call, long_call, credit, credit, max_loss, credit / max_loss if max_loss else float("inf"))

