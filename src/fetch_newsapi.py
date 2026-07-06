from __future__ import annotations

"""Fetch news from NewsAPI."""

import logging
import os
import time as _time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from .http_client import create_session, get_timeout
from .normalize import normalize_newsapi

logger = logging.getLogger(__name__)

NEWSAPI_BASE = "https://newsapi.org/v2"
MAX_RETRIES = 1
RETRY_DELAY = 1
NEWSAPI_PROVIDER_LIMIT_SECONDS = 15

_newsapi_timed_out = False
_provider_deadline = 0.0


def _deadline_reached() -> bool:
    return bool(_provider_deadline and _time.time() >= _provider_deadline)


def _fetch_with_retry(
    url: str,
    params: dict[str, Any],
    config: dict[str, Any],
    retries: int = MAX_RETRIES,
) -> dict[str, Any] | None:
    """Make a GET request with retry. Return JSON dict on success."""
    global _newsapi_timed_out

    session = create_session(config)
    timeout = get_timeout(config, default=(3, 6))

    for attempt in range(1, retries + 1):
        if _deadline_reached():
            logger.warning("NewsAPI provider deadline reached; stopping request")
            return None

        try:
            response = session.get(url, params=params, timeout=timeout)
            response.raise_for_status()

            try:
                data = response.json()
            except ValueError:
                logger.warning("NewsAPI JSON decode failed (attempt %d/%d)", attempt, retries)
                return None

            if data.get("status") == "error":
                code = data.get("code", "")
                message = data.get("message", "")
                logger.warning(
                    "NewsAPI error: [%s] %s (attempt %d/%d)",
                    code,
                    message,
                    attempt,
                    retries,
                )
                return None

            return data

        except requests.exceptions.Timeout:
            _newsapi_timed_out = True
            logger.warning("NewsAPI timeout (attempt %d/%d)", attempt, retries)
            return None

        except requests.exceptions.HTTPError as e:
            response = getattr(e, "response", None)
            status = response.status_code if response is not None else 0
            if status == 426:
                logger.warning(
                    "NewsAPI source unavailable or plan-limited: HTTP 426 (attempt %d/%d)",
                    attempt,
                    retries,
                )
                return None
            logger.warning("NewsAPI HTTP error: status=%s (attempt %d/%d)", status, attempt, retries)
            return None

        except requests.exceptions.RequestException as e:
            response = getattr(e, "response", None)
            status = response.status_code if response is not None else "no_response"
            logger.warning(
                "NewsAPI request failed (attempt %d/%d): %s - %s",
                attempt,
                retries,
                type(e).__name__,
                status,
            )

        if attempt < retries:
            _time.sleep(RETRY_DELAY ** attempt)

    logger.error("NewsAPI exhausted retries")
    return None


def fetch_top_headlines(
    api_key: str,
    sources: list[str],
    config: dict[str, Any],
    page_size: int = 100,
) -> list[dict]:
    """Fetch top headlines from specified NewsAPI source ids."""
    if _deadline_reached():
        logger.warning("NewsAPI provider deadline reached before top-headlines")
        return []

    params = {
        "apiKey": api_key,
        "pageSize": min(page_size, 100),
        "sources": ",".join(sources),
    }
    url = f"{NEWSAPI_BASE}/top-headlines"
    logger.info("Fetching top headlines from %d NewsAPI sources", len(sources))

    data = _fetch_with_retry(url, params, config)
    if not data:
        return []

    raw_articles = data.get("articles", [])
    logger.info("NewsAPI top-headlines returned %d articles", len(raw_articles))

    articles: list[dict] = []
    for raw_article in raw_articles:
        normalized = normalize_newsapi(raw_article)
        if normalized:
            articles.append(normalized)
    return articles


def fetch_everything(
    api_key: str,
    config: dict[str, Any],
    page_size: int = 100,
    hours: int = 24,
    sources: list[str] | None = None,
) -> list[dict]:
    """Fetch /everything results sorted by popularity for the past N hours."""
    if _deadline_reached():
        logger.warning("NewsAPI provider deadline reached before /everything")
        return []

    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    params: dict[str, Any] = {
        "apiKey": api_key,
        "from": since,
        "sortBy": "popularity",
        "pageSize": min(page_size, 100),
        "language": "en",
    }
    if sources:
        params["sources"] = ",".join(sources)

    url = f"{NEWSAPI_BASE}/everything"
    logger.info("Fetching NewsAPI everything (popularity, past %dh)", hours)

    data = _fetch_with_retry(url, params, config)
    if not data:
        return []

    raw_articles = data.get("articles", [])
    logger.info("NewsAPI everything returned %d articles", len(raw_articles))

    articles: list[dict] = []
    for raw_article in raw_articles:
        normalized = normalize_newsapi(raw_article)
        if normalized:
            articles.append(normalized)
    return articles


def fetch_newsapi(config: dict, deadline=None) -> list[dict]:
    """Main entry: fetch from NewsAPI using config."""
    global _newsapi_timed_out, _provider_deadline

    _newsapi_timed_out = False
    started_at = _time.time()
    provider_limit = started_at + NEWSAPI_PROVIDER_LIMIT_SECONDS
    _provider_deadline = min(provider_limit, deadline) if deadline else provider_limit

    if deadline and _time.time() >= deadline:
        logger.warning("Deadline reached before NewsAPI; skipping")
        return []

    api_key = os.getenv("NEWSAPI_KEY")
    if not api_key:
        logger.warning("NEWSAPI_KEY not set — skipping NewsAPI")
        logger.info("NewsAPI status: skipped (0 articles, %.1fs)", _time.time() - started_at)
        return []

    sources_cfg = config.get("sources", {}).get("newsapi", {})
    if not sources_cfg.get("enabled", True):
        logger.info("NewsAPI disabled in config")
        logger.info("NewsAPI status: skipped (0 articles, %.1fs)", _time.time() - started_at)
        return []

    source_ids = sources_cfg.get("sources", [])
    page_size = sources_cfg.get("page_size", 100)

    if not source_ids:
        logger.warning("No NewsAPI sources configured")
        logger.info("NewsAPI status: skipped (0 articles, %.1fs)", _time.time() - started_at)
        return []

    all_articles: list[dict] = []

    articles = fetch_top_headlines(
        api_key=api_key,
        sources=source_ids,
        config=config,
        page_size=page_size,
    )
    if articles:
        all_articles.extend(articles)
    elif _newsapi_timed_out:
        logger.info("NewsAPI timeout; skipping small batches")
        logger.info("NewsAPI /everything skipped due to previous timeout")
        logger.info("NewsAPI status: timeout (%d articles, %.1fs)", len(all_articles), _time.time() - started_at)
        return all_articles
    else:
        logger.info("Batch fetch failed for all NewsAPI sources without timeout; trying smaller batches")
        batch_size = 5
        for i in range(0, len(source_ids), batch_size):
            if _deadline_reached():
                logger.warning("NewsAPI provider deadline reached during batch fetch; stopping")
                break
            batch = source_ids[i:i + batch_size]
            batch_articles = fetch_top_headlines(
                api_key=api_key,
                sources=batch,
                config=config,
                page_size=page_size,
            )
            if batch_articles:
                all_articles.extend(batch_articles)
            if _newsapi_timed_out:
                logger.info("NewsAPI timeout during small batch; stopping")
                break

    if len(all_articles) < 20:
        if _deadline_reached():
            logger.warning("NewsAPI provider deadline reached before /everything; skipping")
        elif _newsapi_timed_out:
            logger.info("NewsAPI /everything skipped due to previous timeout")
        else:
            logger.info("Only %d articles from headlines — supplementing with /everything", len(all_articles))
            extra_articles = fetch_everything(
                api_key=api_key,
                config=config,
                page_size=max(page_size, 100),
                sources=source_ids if source_ids else None,
            )
            if extra_articles:
                all_articles.extend(extra_articles)

    duration = _time.time() - started_at
    if _newsapi_timed_out:
        logger.info("NewsAPI status: timeout (%d articles, %.1fs)", len(all_articles), duration)
    else:
        logger.info("NewsAPI status: success (%d articles, %.1fs)", len(all_articles), duration)

    return all_articles
