from dataclasses import dataclass
from .models import OptionQuote

@dataclass(frozen=True)
class MonitoringAlert:
    underlying_stop_breached: bool
    delta_breached: bool
    premium_multiple_breached: bool
    gamma_breached: bool
    spread_breached: bool
    alerts: tuple[str, ...]

def monitor_short_call(current: OptionQuote, entry_spot: float, entry_premium: float, underlying_stop: float, stop_delta: float = 0.35, premium_stop_multiple: float = 2.0, max_gamma: float | None = None, max_spread_pct: float = 0.20) -> MonitoringAlert:
    """Create alerts for a tracked call; it never places or modifies trades."""
    mid = (current.bid + current.ask) / 2 if current.bid > 0 and current.ask >= current.bid else current.ltp
    spread = ((current.ask - current.bid) / mid) if mid > 0 and current.ask >= current.bid else float("inf")
    underlying = current.spot >= underlying_stop
    delta = current.delta is not None and abs(current.delta) >= stop_delta
    premium = entry_premium > 0 and mid >= entry_premium * premium_stop_multiple
    gamma = max_gamma is not None and current.gamma is not None and current.gamma >= max_gamma
    spread_alert = spread > max_spread_pct
    alerts = []
    if underlying: alerts.append("underlying crossed volatility stop-loss")
    if delta: alerts.append("absolute delta crossed configured alert")
    if premium: alerts.append("option premium reached configured multiple of tracked entry")
    if gamma: alerts.append("gamma crossed configured alert")
    if spread_alert: alerts.append("bid-ask spread exceeded configured limit")
    return MonitoringAlert(underlying, delta, premium, gamma, spread_alert, tuple(alerts))
