from dataclasses import dataclass
from enum import Enum
import math

class MarketPosture(str, Enum):
    ALLOW = "allow"
    RESTRICT = "restrict"
    CASH_PRIORITY = "cash-priority"

@dataclass(frozen=True)
class MarketFilterDecision:
    posture: MarketPosture
    score: int
    nifty_above_sma50: bool
    nifty_above_sma200: bool
    breadth_above_sma50: float
    volatility_spike: bool
    india_vix: float | None
    vix_elevated: bool
    vix_extreme: bool
    reasons: tuple[str, ...]

def _sma(values: list[float], period: int) -> float | None:
    return sum(values[-period:]) / period if len(values) >= period else None

def _annualized_vol(closes: list[float], window: int = 20) -> float | None:
    if len(closes) < window + 1:
        return None
    returns = [math.log(b / a) for a, b in zip(closes[-window - 1:], closes[-window:]) if a > 0 and b > 0]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    return math.sqrt(sum((x - mean) ** 2 for x in returns) / (len(returns) - 1) * 252)

def evaluate_market_filter(nifty_closes: list[float], stock_closes: dict[str, list[float]], india_vix_closes: list[float] | None = None, min_breadth: float = 0.50, max_volatility_ratio: float = 1.50, vix_elevated_level: float = 20.0, vix_extreme_level: float = 25.0, vix_elevated_ratio: float = 1.20, vix_extreme_ratio: float = 1.40) -> MarketFilterDecision:
    """Evaluate whether new call-writing research should be allowed.

    This is a local NSE proxy for the referenced toolkit's market-regime gate:
    NIFTY trend, watchlist participation breadth, and volatility stress.
    Missing data fails closed to RESTRICT rather than allowing new risk.
    """
    reasons: list[str] = []
    nifty_sma50 = _sma(nifty_closes, 50)
    nifty_sma200 = _sma(nifty_closes, 200)
    if nifty_sma50 is None or nifty_sma200 is None or not nifty_closes:
        return MarketFilterDecision(MarketPosture.RESTRICT, 0, False, False, 0.0, True, None, False, True, ("insufficient NIFTY history",))
    nifty_last = nifty_closes[-1]
    above50 = nifty_last > nifty_sma50
    above200 = nifty_last > nifty_sma200
    if not above50: reasons.append("NIFTY below 50-day SMA")
    if not above200: reasons.append("NIFTY below 200-day SMA")

    eligible = 0
    participating = 0
    for closes in stock_closes.values():
        sma50 = _sma(closes, 50)
        if sma50 is not None and closes:
            eligible += 1
            participating += int(closes[-1] > sma50)
    breadth = participating / eligible if eligible else 0.0
    if breadth < min_breadth: reasons.append(f"watchlist breadth below {min_breadth:.0%}")

    short_vol = _annualized_vol(nifty_closes, 20)
    long_vol = _annualized_vol(nifty_closes, 100)
    vol_spike = short_vol is None or long_vol is None or short_vol > long_vol * max_volatility_ratio
    if vol_spike: reasons.append("NIFTY volatility stress/spike")

    current_vix = india_vix_closes[-1] if india_vix_closes else None
    vix_sma20 = _sma(india_vix_closes, 20) if india_vix_closes else None
    vix_elevated = bool(current_vix is not None and (current_vix >= vix_elevated_level or (vix_sma20 and current_vix >= vix_sma20 * vix_elevated_ratio)))
    vix_extreme = bool(current_vix is not None and (current_vix >= vix_extreme_level or (vix_sma20 and current_vix >= vix_sma20 * vix_extreme_ratio)))
    if vix_extreme:
        reasons.append("India VIX is at an extreme level")
    elif vix_elevated:
        reasons.append("India VIX is elevated")

    score = int(40 * above50 + 30 * above200 + 30 * (breadth >= min_breadth))
    if vol_spike:
        score = max(0, score - 20)
    if vix_extreme:
        posture = MarketPosture.CASH_PRIORITY
    elif score >= 70 and not vol_spike and not vix_elevated:
        posture = MarketPosture.ALLOW
    elif score >= 40:
        posture = MarketPosture.RESTRICT
    else:
        posture = MarketPosture.CASH_PRIORITY
    return MarketFilterDecision(posture, score, above50, above200, breadth, vol_spike, current_vix, vix_elevated, vix_extreme, tuple(reasons) or ("market conditions pass the configured gate",))

