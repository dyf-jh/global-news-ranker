from __future__ import annotations

"""Fetch news from RSS feeds.

RSS is the main resilient data source for the current project. Feed entries
may be configured either as strings or as dictionaries with metadata:

sources:
  rss:
    feeds:
      - name: BBC World
        source: bbc-news
        url: http://feeds.bbci.co.uk/news/world/rss.xml
        enabled: true
        category: world
        country: GB
        language: en
"""

import logging
import time as _time
from typing import Any
from urllib.parse import urlparse

import requests

from .http_client import create_session, get_timeout
from .normalize import normalize_rss

logger = logging.getLogger(__name__)

MAX_RETRIES = 1
RETRY_DELAY = 1


def _normalise_feed_config(feed: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(feed, str):
        return {
            "name": urlparse(feed).netloc or feed,
            "source": urlparse(feed).netloc or feed,
            "url": feed,
            "enabled": True,
            "category": "general",
            "country": "",
            "language": "en",
        }
    item = dict(feed)
    item.setdefault("enabled", True)
    item.setdefault("source", item.get("name") or item.get("url", "rss"))
    item.setdefault("name", item.get("source"))
    item.setdefault("language", "en")
    item.setdefault("category", "general")
    item.setdefault("country", "")
    return item


def _fetch_feed(url: str, config: dict[str, Any], retries: int = MAX_RETRIES) -> bytes | None:
    """Download raw RSS/Atom feed XML with retry."""
    session = create_session(config)
    timeout = get_timeout(config, default=(5, 12))

    for attempt in range(1, retries + 1):
        try:
            resp = session.get(
                url,
                timeout=timeout,
                headers={"User-Agent": "Mozilla/5.0 (compatible; GlobalNewsRanker/1.0)"},
            )
            resp.raise_for_status()
            return resp.content
        except requests.exceptions.Timeout:
            domain = urlparse(url).netloc
            logger.warning("RSS timeout for %s (attempt %d/%d)", domain, attempt, retries)
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            domain = urlparse(url).netloc
            logger.warning("RSS HTTP %d for %s (attempt %d/%d)", status, domain, attempt, retries)
        except requests.exceptions.RequestException as e:
            logger.warning("RSS request failed: %s (attempt %d/%d)", e, attempt, retries)

        if attempt < retries:
            _time.sleep(RETRY_DELAY)

    domain = urlparse(url).netloc
    logger.error("RSS exhausted retries for %s", domain)
    return None


def fetch_rss(config: dict, deadline=None) -> list[dict]:
    """Fetch articles from configured RSS/Atom feeds. Returns normalized articles."""
    if deadline and _time.time() > deadline:
        logger.info("  RSS status: skipped (deadline exceeded)")
        return []

    started_at = _time.time()
    rss_cfg = config.get("sources", {}).get("rss", {})
    if not rss_cfg.get("enabled", True):
        logger.info("RSS disabled in config")
        return []

    feed_items = [_normalise_feed_config(f) for f in rss_cfg.get("feeds", [])]
    enabled_feeds = [f for f in feed_items if f.get("enabled", True) and f.get("url")]

    if not enabled_feeds:
        logger.warning("No enabled RSS feeds configured")
        return []

    all_articles: list[dict] = []
    success_count = 0

    for feed in enabled_feeds:
        if deadline and _time.time() > deadline:
            logger.info("  RSS deadline reached; stopping feed fetch")
            break

        feed_url = feed["url"]
        source_id = feed.get("source") or feed.get("name") or feed_url
        try:
            content = _fetch_feed(feed_url, config)
            if content is None:
                continue

            import feedparser
            parsed = feedparser.parse(content)
            if parsed.bozo and not parsed.entries:
                domain = urlparse(feed_url).netloc
                logger.warning("RSS parse error for %s: %s", domain, parsed.bozo_exception)
                continue

            feed_title = parsed.feed.get("title", feed.get("name", feed_url)) if hasattr(parsed, "feed") else feed.get("name", feed_url)
            entries = parsed.entries or []
            success_count += 1
            logger.info("RSS feed '%s' [%s] returned %d entries", feed.get("name", feed_title), source_id, len(entries))

            for entry in entries:
                normalized = normalize_rss(entry, feed_url)
                if normalized:
                    normalized["source"] = source_id
                    normalized["source_name"] = feed.get("name", feed_title)
                    normalized["category"] = feed.get("category", "general")
                    normalized["country"] = feed.get("country", normalized.get("country", ""))
                    normalized["language"] = feed.get("language", normalized.get("language", "en"))
                    all_articles.append(normalized)

        except Exception as e:
            domain = urlparse(feed_url).netloc
            logger.warning("Failed to process RSS feed %s: %s", domain, str(e)[:120])
            continue

    logger.info(
        "RSS total: %d articles from %d/%d enabled feeds, %.1fs",
        len(all_articles),
        success_count,
        len(enabled_feeds),
        _time.time() - started_at,
    )
    return all_articles
