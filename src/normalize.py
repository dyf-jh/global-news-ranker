from __future__ import annotations
"""Normalize raw articles from various providers into a unified schema."""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _parse_newsapi_timestamp(ts: str) -> str:
    """Parse NewsAPI ISO 8601 timestamp to a consistent format."""
    if not ts:
        return datetime.now(timezone.utc).isoformat()
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.isoformat()
    except (ValueError, TypeError):
        return datetime.now(timezone.utc).isoformat()


def _parse_gdelt_timestamp(ts: str) -> str:
    """Parse GDELT seendate (YYYYMMDDHHMMSS) to ISO 8601."""
    if not ts or len(ts) < 14:
        return datetime.now(timezone.utc).isoformat()
    try:
        dt = datetime.strptime(ts[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except (ValueError, TypeError):
        return datetime.now(timezone.utc).isoformat()


def _extract_country(domain: str) -> str:
    """Crude country guess from domain TLD (not primary logic)."""
    mapping = {
        "co.uk": "GB",
        "com.au": "AU",
        "ca": "CA",
        "de": "DE",
        "fr": "FR",
        "jp": "JP",
    }
    for suffix, code in mapping.items():
        if domain.endswith("." + suffix):
            return code
    return "US"


def _extract_source_name(source_obj) -> str:
    """Extract source name from NewsAPI source object or string."""
    if isinstance(source_obj, dict):
        return source_obj.get("id") or source_obj.get("name", "unknown")
    if isinstance(source_obj, str):
        return source_obj
    return "unknown"


def normalize_newsapi(article: dict) -> dict | None:
    """Normalize a single NewsAPI article."""
    try:
        title = (article.get("title") or "").strip()
        url = (article.get("url") or "").strip()
        if not title or not url:
            return None
        return {
            "title": title,
            "description": (article.get("description") or "").strip(),
            "url": url,
            "source": _extract_source_name(article.get("source", {})),
            "published_at": _parse_newsapi_timestamp(article.get("publishedAt")),
            "language": "en",
            "country": _extract_country(url.split("/")[2] if "//" in url else ""),
            "raw_provider": "newsapi",
        }
    except Exception as e:
        logger.warning("Failed to normalize NewsAPI article: %s", e)
        return None


def normalize_gdelt(article: dict) -> dict | None:
    """Normalize a single GDELT DOC 2.0 article."""
    try:
        title = (article.get("title") or "").strip()
        url = (article.get("url") or "").strip()
        if not title or not url:
            return None
        domain = article.get("domain", "")
        seendate = article.get("seendate", "")
        return {
            "title": title,
            "description": "",
            "url": url,
            "source": domain or "gdelt",
            "published_at": _parse_gdelt_timestamp(seendate),
            "language": (article.get("language") or "en").lower()[:2],
            "country": _extract_country(domain),
            "raw_provider": "gdelt",
        }
    except Exception as e:
        logger.warning("Failed to normalize GDELT article: %s", e)
        return None


def normalize_rss(entry, feed_url: str) -> dict | None:
    """Normalize a single RSS feed entry."""
    try:
        title = (getattr(entry, "title", "") or "").strip()
        link = (getattr(entry, "link", "") or "").strip()
        if not title or not link:
            return None
        summary = (getattr(entry, "summary", "") or "").strip()
        # Extract source from feed title or URL
        source = feed_url

        # Parse published time
        published = datetime.now(timezone.utc)
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            import time
            try:
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass
        elif hasattr(entry, "published") and entry.published:
            try:
                published = datetime.fromisoformat(entry.published.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        return {
            "title": title,
            "description": summary,
            "url": link,
            "source": source,
            "published_at": published.isoformat(),
            "language": "en",
            "country": "US",
            "raw_provider": "rss",
        }
    except Exception as e:
        logger.warning("Failed to normalize RSS entry: %s", e)
        return None


def normalize_article(article, provider: str, **kwargs) -> dict | None:
    """Dispatch to the correct normalizer based on provider."""
    if provider == "newsapi":
        return normalize_newsapi(article)
    elif provider == "gdelt":
        return normalize_gdelt(article)
    elif provider == "rss":
        return normalize_rss(article, kwargs.get("feed_url", ""))
    logger.warning("Unknown provider: %s", provider)
    return None
