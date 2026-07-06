from __future__ import annotations

"""Fetch news from the GDELT DOC 2.0 API."""

import logging
import time as _time
from typing import Any

import requests

from .http_client import create_session, get_timeout
from .normalize import normalize_gdelt

logger = logging.getLogger(__name__)

GDELT_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"
MAX_RETRIES = 1
RETRY_DELAY = 1


def _fetch_with_retry(params: dict[str, Any], config: dict[str, Any], retries: int = MAX_RETRIES) -> dict | None:
    """Query GDELT DOC 2.0 with retry logic."""
    session = create_session(config)
    timeout = get_timeout(config, default=(5, 12))

    for attempt in range(1, retries + 1):
        try:
            resp = session.get(GDELT_BASE, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            logger.warning("GDELT timeout (attempt %d/%d)", attempt, retries)
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            logger.warning("GDELT HTTP %d (attempt %d/%d)", status, attempt, retries)
        except requests.exceptions.RequestException as e:
            logger.warning("GDELT request failed (attempt %d/%d): %s", attempt, retries, type(e).__name__)
        except ValueError as e:
            logger.warning("GDELT JSON decode failed (attempt %d/%d): %s", attempt, retries, type(e).__name__)

        if attempt < retries:
            _time.sleep(RETRY_DELAY ** attempt)

    logger.error("GDELT exhausted retries")
    return None


def fetch_gdelt(config: dict, deadline=None) -> list[dict]:
    """Fetch articles from GDELT DOC 2.0. Returns normalized articles."""
    if deadline and _time.time() > deadline:
        logger.info("  GDELT status: skipped (deadline exceeded)")
        return []

    started_at = _time.time()
    gdelt_cfg = config.get("sources", {}).get("gdelt", {})
    if not gdelt_cfg.get("enabled", True):
        logger.info("GDELT disabled in config")
        return []

    max_articles = gdelt_cfg.get("max_articles", 150)
    domains = gdelt_cfg.get("domains", [])
    domain_restrict = gdelt_cfg.get("domain_restrict", True)

    params: dict[str, Any] = {
        "mode": "artlist",
        "format": "json",
        "maxrecords": min(max_articles, 250),
        "timespan": "24h",
        "sort": "DateDesc",
    }

    # Keep the existing project behavior. Some GDELT calls may still time out;
    # it remains a supplement, not the first source of truth.
    if domain_restrict and domains:
        params["domain"] = " ".join(domains)

    logger.info("Fetching GDELT (max %d, domains: %s)", max_articles, domain_restrict)
    data = _fetch_with_retry(params, config)
    if data is None:
        return []

    raw = data.get("articles", []) or data.get("results", [])
    if not raw:
        logger.warning("GDELT returned no articles")
        return []

    logger.info("GDELT returned %d raw articles", len(raw))
    articles = []
    for a in raw:
        normalized = normalize_gdelt(a)
        if normalized:
            articles.append(normalized)

    logger.info("GDELT total: %d articles, %.1fs", len(articles), _time.time() - started_at)
    return articles
