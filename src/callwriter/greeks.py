import math

def _cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def annualized_historical_vol(closes: list[float], trading_days: int = 252) -> float:
    if len(closes) < 2 or any(x <= 0 for x in closes):
        raise ValueError("At least two positive closing prices are required")
    returns = [math.log(b / a) for a, b in zip(closes, closes[1:])]
    if len(returns) < 2:
        raise ValueError("At least three closes are required for sample volatility")
    mean = sum(returns) / len(returns)
    variance = sum((x - mean) ** 2 for x in returns) / (len(returns) - 1)
    return math.sqrt(variance * trading_days)

def mean_log_return(closes: list[float]) -> float:
    if len(closes) < 2 or any(x <= 0 for x in closes):
        raise ValueError("At least two positive closing prices are required")
    returns = [math.log(b / a) for a, b in zip(closes, closes[1:])]
    return sum(returns) / len(returns)

def volatility_range(spot: float, daily_mean: float, annualized_vol: float, trading_days_to_expiry: int, deviations: float = 1.0, trading_days: int = 252) -> tuple[float, float]:
    """Varsity-style log-return range for the underlying until expiry."""
    if min(spot, annualized_vol, trading_days_to_expiry) <= 0 or deviations < 0:
        raise ValueError("spot, volatility, days and deviations must be positive")
    time = float(trading_days_to_expiry)
    daily_vol = annualized_vol / math.sqrt(trading_days)
    centre = daily_mean * time
    spread = deviations * daily_vol * math.sqrt(time)
    return spot * math.exp(centre - spread), spot * math.exp(centre + spread)

def call_delta(spot: float, strike: float, dte_years: float, iv: float, rate: float = 0.06) -> float:
    if min(spot, strike, dte_years, iv) <= 0:
        return 1.0 if spot > strike else 0.0
    d1 = (math.log(spot / strike) + (rate + iv * iv / 2) * dte_years) / (iv * math.sqrt(dte_years))
    return _cdf(d1)

def probability_below_strike(spot: float, strike: float, dte_years: float, vol: float, rate: float = 0.06) -> float:
    if dte_years <= 0 or vol <= 0:
        return float(spot < strike)
    d2 = (math.log(spot / strike) + (rate - vol * vol / 2) * dte_years) / (vol * math.sqrt(dte_years))
    return _cdf(-d2)

