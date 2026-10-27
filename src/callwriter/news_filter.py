from dataclasses import dataclass
from datetime import datetime, timezone
import re

@dataclass(frozen=True)
class NewsRisk:
    symbol: str
    headline: str
    published_time_ms: int
    severity: str
    reasons: tuple[str, ...]

@dataclass(frozen=True)
class NewsFilterDecision:
    blocked_symbols: frozenset[str]
    restricted_symbols: frozenset[str]
    risks: tuple[NewsRisk, ...]
    data_available: bool = True

_BLOCK_KEYWORDS = {
    "earnings", "results", "quarterly", "dividend", "bonus", "split", "rights issue",
    "buyback", "merger", "acquisition", "demerger", "default", "fraud", "investigation",
    "resignation", "credit rating", "insolvency", "ban", "penalty", "downgrade",
}
_RESTRICT_KEYWORDS = {
    "order win", "contract", "guidance", "regulatory", "approval", "stake sale",
    "fund raising", "fundraising", "promoter", "pledge", "block deal", "ipo",
}

def _matched_keywords(text: str, keywords: set[str]) -> tuple[str, ...]:
    """Match complete words/phrases so `ban` does not match `bank`."""
    return tuple(
        keyword
        for keyword in keywords
        if re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", text)
    )

def _published_ms(item: dict) -> int:
    value = item.get("published_time", 0)
    return int(value or 0)

def evaluate_news_filter(news_by_symbol: dict[str, list[dict]], now: datetime | None = None, block_hours: int = 48, restrict_hours: int = 168) -> NewsFilterDecision:
    """Classify recent instrument news; this is a risk gate, not sentiment prediction."""
    now = now or datetime.now(timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    blocked: set[str] = set()
    restricted: set[str] = set()
    risks: list[NewsRisk] = []
    for symbol, items in news_by_symbol.items():
        for item in items:
            published = _published_ms(item)
            age_hours = (now_ms - published) / 3_600_000 if published else float("inf")
            text = f"{item.get('heading', '')} {item.get('summary', '')}".lower()
            block_reasons = _matched_keywords(text, _BLOCK_KEYWORDS)
            restrict_reasons = _matched_keywords(text, _RESTRICT_KEYWORDS)
            if block_reasons and age_hours <= block_hours:
                blocked.add(symbol)
                risks.append(NewsRisk(symbol, item.get("heading", ""), published, "block", block_reasons))
            elif (block_reasons or restrict_reasons) and age_hours <= restrict_hours:
                restricted.add(symbol)
                risks.append(NewsRisk(symbol, item.get("heading", ""), published, "restrict", block_reasons or restrict_reasons))
    return NewsFilterDecision(frozenset(blocked), frozenset(restricted), tuple(risks))

