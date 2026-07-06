"""Temporal filter: keep only articles published within the last N hours."""
import logging
import re
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def filter_recent_articles(articles, hours=24):
    """Keep articles whose published_at is within the last `hours`.

    Articles without a parseable published_at are discarded.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)

    kept = []
    dropped_no_date = 0
    dropped_old = 0

    for art in articles:
        pub_str = art.get("published_at", "")
        if not pub_str:
            dropped_no_date += 1
            continue
        try:
            pub = datetime.fromisoformat(pub_str)
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            dropped_no_date += 1
            continue

        if pub < cutoff:
            dropped_old += 1
            continue

        kept.append(art)

    logger.info("before time filter: %d", len(articles))
    logger.info("after time filter: %d", len(kept))
    if dropped_no_date:
        logger.info("dropped missing published_at: %d", dropped_no_date)
    if dropped_old:
        logger.info("dropped too old: %d", dropped_old)

    return kept



HARD_NEWS_KEYWORDS = [
    "federal reserve", "fed", "interest rates", "inflation",
    "central bank", "election", "supreme court", "court",
    "sanctions", "war", "conflict", "trade", "tariffs",
    "artificial intelligence", "chip", "semiconductor", "cyberattack",
    "oil", "energy", "disaster", "heat wave", "climate",
    "diplomacy", "government", "congress", "president",
    "prime minister", "economy", "gdp", "jobs report",
    "labor market", "tesla", "kroger", "scotus",
]


STRONG_LOW_VALUE_KEYWORDS = {
    "world cup", "nba", "nfl", "football", "soccer",
    "box office", "blockbuster movie", "opening weekend",
    "movie", "film", "netflix", "dating",
    "celebrity", "singer", "frontman", "actor", "actress",
    "trailer",
    "lottery", "horoscope", "fashion",
    "real estate", "personal finance", "retirement", "social security",
    "live:", "abc news live",
    "daughter", "mother-in-law", "inheritance", "poverty",
    "autism", "drowning", "student loan", "borrowers",
    "personal story", "family finance",
    "my daughter", "my kid", "your children",
    "trump account", "inheritance",

}


LOW_VALUE_KEYWORDS = {
    "sports", "world cup", "nba", "nfl", "football", "soccer",
    "celebrity", "singer", "frontman", "co-writer", "village people",
    "movie", "tv", "netflix", "dating",
    "real estate", "lifestyle", "horoscope", "lottery", "fashion",
    "social security", "personal finance", "retirement",
    "stock market open", "market holiday",
    "movie star", "pop star", "music star", "hollywood star", "celebrity star",
    "health tips", "safety tips",
}


def filter_low_value_articles(articles):
    """Filter low-value articles with hard news whitelist protection."""
    kept = []
    dropped = 0
    first_10 = []
    for art in articles:
        text = (
            art.get("title", "") + " "
            + art.get("description", "") + " "
            + art.get("source", "") + " "
            + art.get("category", "")
        ).lower()
        # 1. Strong low-value keywords - always drop
        # Check title prefix for WATCH:/LIVE:
        title_lower = (art.get("title") or "").lower()
        if title_lower.startswith("watch:") or title_lower.startswith("live:"):
            if len(first_10) < 10:
                first_10.append(str(art.get("title", ""))[:60] + " | matched=" + title_lower.split(":")[0] + " | reason=strong_low_value")
            dropped += 1
            continue
        matched_sk = None
        for sk in STRONG_LOW_VALUE_KEYWORDS:
            if re.search(r"\b" + re.escape(sk) + r"\b", text):
                matched_sk = sk
                break
        if matched_sk:
            if len(first_10) < 10:
                first_10.append(str(art.get("title", ""))[:60] + " | matched=" + matched_sk + " | reason=strong_low_value")
            dropped += 1
            continue
        # 2. Hard news whitelist
        if any(hk in text for hk in HARD_NEWS_KEYWORDS):
            kept.append(art)
            continue
        # 3. Regular low-value keywords
        if any(kw in text for kw in LOW_VALUE_KEYWORDS):
            if len(first_10) < 10:
                first_10.append(str(art.get("title", ""))[:60])
            dropped += 1
            continue
        kept.append(art)
    logger.info("before low-value filter: %d", len(articles))
    logger.info("after low-value filter: %d", len(kept))
    if dropped:
        logger.info("dropped low-value: %d", dropped)
        for t in first_10:
            logger.info("  dropped low-value title: %s", t)
    return kept
