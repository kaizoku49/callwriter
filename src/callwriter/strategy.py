from dataclasses import dataclass
from datetime import date
from .greeks import call_delta, probability_below_strike, volatility_range
from .models import Candidate, OptionQuote
from .market_filter import MarketFilterDecision
from .news_filter import NewsFilterDecision

@dataclass(frozen=True)
class StrategyConfig:
    min_dte: float = 1.0
    max_dte: float = 10.0
    range_deviations: float = 1.0
    max_delta: float | None = 0.25
    min_premium_yield: float = 0.001
    min_oi: int = 0
    min_volume: int = 1
    min_bid_qty: int = 1
    min_ask_qty: int = 1
    max_spread_pct: float = 0.20
    min_iv_hv_ratio: float = 0.90
    max_iv_hv_ratio: float = 2.00
    max_iv_skew: float = 0.15
    max_term_structure_ratio: float = 1.50
    require_iv: bool = True
    max_gamma: float | None = None
    risk_free_rate: float = 0.06

def _weekdays_between(start: date, end: date) -> int:
    return sum((start.fromordinal(day).weekday() < 5) for day in range(start.toordinal(), end.toordinal() + 1))

def _same_expiry_atm_iv(quotes: list[OptionQuote], quote: OptionQuote) -> float | None:
    same_expiry = [q for q in quotes if q.expiry == quote.expiry and q.iv is not None]
    if not same_expiry:
        return None
    return min(same_expiry, key=lambda q: abs(q.strike - q.spot)).iv

def _term_structure_ratio(quotes: list[OptionQuote], quote: OptionQuote) -> float | None:
    expiries = sorted({q.expiry for q in quotes if q.iv is not None})
    later = [expiry for expiry in expiries if expiry > quote.expiry]
    if not later:
        return None
    current_iv = _same_expiry_atm_iv(quotes, quote)
    next_quotes = [q for q in quotes if q.expiry == later[0] and q.iv is not None]
    if current_iv is None or not next_quotes:
        return None
    next_iv = min(next_quotes, key=lambda q: abs(q.strike - q.spot)).iv
    return current_iv / next_iv if next_iv else None

def rank_calls(quotes: list[OptionQuote], historical_vol: float, as_of: date, daily_mean_log_return: float = 0.0, config: StrategyConfig = StrategyConfig(), market_filter: MarketFilterDecision | None = None, news_filter: NewsFilterDecision | None = None) -> list[Candidate]:
    # The broad NIFTY trend/breadth market gate is informational only. Keep
    # the independent VIX safety filter because the tracker is intended to
    # flag sudden volatility risk without hiding every candidate in a weak
    # trend regime.
    if market_filter and market_filter.vix_extreme:
        return []
    results = []
    for q in quotes:
        if news_filter and q.underlying in news_filter.blocked_symbols:
            continue
        dte = (q.expiry - as_of).total_seconds() / 86400
        trading_dte = _weekdays_between(as_of, q.expiry) - (1 if as_of.weekday() < 5 else 0)
        if not (config.min_dte <= dte <= config.max_dte and q.strike > q.spot and q.oi >= config.min_oi and trading_dte > 0):
            continue
        if q.volume < config.min_volume or q.bid_qty < config.min_bid_qty or q.ask_qty < config.min_ask_qty:
            continue
        if q.bid <= 0 or q.ask <= 0 or q.ask < q.bid:
            continue
        mid = (q.bid + q.ask) / 2
        if (q.ask - q.bid) / mid > config.max_spread_pct:
            continue
        if config.require_iv and q.iv is None:
            continue
        lower_range, upper_range = volatility_range(q.spot, daily_mean_log_return, historical_vol, trading_dte, config.range_deviations)
        stop_loss_breached = q.spot >= upper_range
        if q.strike < upper_range:
            continue
        iv = q.iv or historical_vol
        iv_hv_ratio = iv / historical_vol if historical_vol else 0.0
        if not (config.min_iv_hv_ratio <= iv_hv_ratio <= config.max_iv_hv_ratio):
            continue
        atm_iv = _same_expiry_atm_iv(quotes, q)
        iv_skew = iv - atm_iv if atm_iv is not None else None
        if iv_skew is not None and iv_skew > config.max_iv_skew:
            continue
        term_ratio = _term_structure_ratio(quotes, q)
        if term_ratio is not None and term_ratio > config.max_term_structure_ratio:
            continue
        years = max(trading_dte / 252, 1 / 3650)
        delta = q.delta if q.delta is not None else call_delta(q.spot, q.strike, years, iv, config.risk_free_rate)
        if config.max_delta is not None and delta > config.max_delta:
            continue
        yield_on_spot = mid / q.spot if q.spot else 0
        if yield_on_spot < config.min_premium_yield:
            continue
        otm_prob = probability_below_strike(q.spot, q.strike, years, historical_vol, config.risk_free_rate)
        move = q.spot * historical_vol * (years ** 0.5)
        distance_from_range = (q.strike - upper_range) / q.spot
        # Varsity is range-first: stay close to the upper range, then prefer
        # the better premium among nearby strikes. This prevents a distant,
        # low-probability strike from winning solely on premium yield.
        score = yield_on_spot * 1000 - distance_from_range * 10000
        warnings = []
        if market_filter and market_filter.vix_elevated:
            warnings.append("India VIX is elevated; sudden-move risk is higher")
        if news_filter and q.underlying in news_filter.restricted_symbols:
            warnings.append("recent material news restricts new risk")
        if stop_loss_breached:
            warnings.append("underlying is at or beyond the volatility stop-loss")
        if q.iv and q.iv > historical_vol * 1.5: warnings.append("IV much higher than historical volatility")
        if config.max_gamma is not None and q.gamma is not None and q.gamma > config.max_gamma: warnings.append("gamma above configured limit")
        if dte <= 2: warnings.append("near-expiry gamma/settlement risk")
        results.append(Candidate(q, dte, historical_vol, otm_prob, move, upper_range, upper_range, stop_loss_breached, iv_hv_ratio, iv_skew, term_ratio, yield_on_spot, score, tuple(warnings)))
    return sorted(results, key=lambda x: x.score, reverse=True)

