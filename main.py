#!/usr/bin/env python3
from __future__ import annotations

"""Global News Ranker - daily top 20 news from international media.

Pipeline:
  1. Load configuration and environment variables
  2. Fetch articles (NewsAPI -> GDELT -> RSS, all providers tried)
  3. Normalize and deduplicate
  4. Cluster by event similarity
  5. Rank by hot_score
  6. Export top N to JSON / CSV / Markdown
  7. Notify (placeholder)
"""
import argparse
import time
import logging
import os
import sys
import traceback

from datetime import datetime, timedelta, timezone

import yaml
import requests
from urllib.parse import urlparse

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv() -> None:
        """No-op fallback when python-dotenv is not installed."""
        pass

from src.filter import filter_recent_articles, filter_low_value_articles
from src.fetch_newsapi import fetch_newsapi
from src.fetch_gdelt import fetch_gdelt
from src.fetch_rss import fetch_rss, _normalise_feed_config
from src.deduplicate import deduplicate, cluster_events
from src.ranker import rank_events
from src.exporter import export_all
from src.notifier import notify, notify_error
from src.http_client import create_session, get_timeout


logger = logging.getLogger(__name__)


def parse_args(argv=None):
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(description="Global News Ranker")
    p.add_argument("--dry-run", action="store_true",
                   help="Run with mock data, skip external API calls")
    p.add_argument("--diagnose-sources", action="store_true",
                   help="Diagnose NewsAPI, GDELT, and RSS sources without running the full pipeline")
    return p.parse_args(argv)


def load_config(path="config.yaml"):
    """Load the YAML configuration file."""
    if not os.path.exists(path):
        print(f"[FATAL] Config file not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def setup_logging(config):
    """Configure logging based on config settings."""
    log_cfg = config.get("logging", {})
    level_str = log_cfg.get("level", "INFO").upper()
    level = getattr(logging, level_str, logging.INFO)

    handlers = [logging.StreamHandler(sys.stdout)]

    log_file = log_cfg.get("file")
    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


def generate_mock_articles():
    """Generate at least 30 mock articles for dry-run mode.

    Covers: same-event clusters, varied recency, duplicate titles,
    low-weight sources, and all major topic categories.
    """
    now = datetime.now(timezone.utc)

    raw = [
        # Event 1: War - Ukraine (cluster of 4)
        ("Ukraine Launches Major Military Offensive in Eastern Ukraine","Ukrainian forces launched a major offensive.","https://reuters.com/world/ukraine-offensive","reuters",1),
        ("Ukraine Launches Major Offensive in Eastern Ukraine Region","The Ukrainian military announced a large-scale operation.","https://bbc.com/news/world/ukraine-offensive","bbc-news",2),
        ("Ukraine Launches Major Military Offensive in East","Ukraine has begun a significant military operation.","https://cnn.com/world/ukraine-offensive","cnn",3),
        ("Ukraine Launches Major Offensive, Military Officials Say","A major Ukrainian military offensive is underway.","https://apnews.com/ukraine-offensive","associated-press",4),
        # Event 2: AI - GPT-5 (cluster of 2)
        ("OpenAI Unveils GPT-5: A New Era of Artificial Intelligence","OpenAI has released GPT-5.","https://bloomberg.com/tech/openai-gpt5","bloomberg",5),
        ("OpenAI Unveils GPT-5: New Era of Artificial Intelligence Now","The latest LLM from OpenAI promises breakthroughs.","https://theverge.com/gpt5","the-verge",6),
        # Event 3: Election - US 2026 (cluster of 3)
        ("US Presidential Election 2026: Key Battleground States","Swing states see intense campaign activity.","https://washingtonpost.com/politics/election2026","the-washington-post",2),
        ("US Presidential Election 2026: Key Swing States to Watch","Both parties are ramping up efforts.","https://politico.com/election2026","politico",3),
        ("US Presidential Election 2026: Key States in Focus","Primaries set the stage for the November election.","https://thehill.com/primaries","the-hill",8),
        # Event 4: Financial Markets - Fed rates (cluster of 3)
        ("Federal Reserve Holds Interest Rates Steady Amid Inflation","The Fed maintained its benchmark rate.","https://ft.com/fed-rates","financial-times",4),
        ("Federal Reserve Holds Interest Rates Steady, Signals Caution","The central bank kept rates unchanged.","https://bloomberg.com/markets/fed-hold","bloomberg",5),
        ("Federal Reserve Holds Interest Rates Unchanged at 5.25","The Fed voted to hold rates steady.","https://reuters.com/markets/fed-decision","reuters",6),
        # Event 5: Disaster - Japan earthquake (cluster of 2)
        ("Powerful Earthquake Strikes Japan, Tsunami Warning Issued","A 7.3 magnitude earthquake hit off the coast of Japan.","https://aljazeera.com/news/japan-quake","al-jazeera-english",2),
        ("Powerful Earthquake Hits Japan, Tsunami Warning Issued","A major earthquake struck Japan.","https://cnn.com/world/japan-quake","cnn",3),
        # Event 6: Trade - US-China talks (cluster of 2)
        ("US and China Resume High-Level Trade Talks in Geneva","Senior officials met to discuss tariff reductions.","https://reuters.com/world/us-china-trade","reuters",6),
        ("US and China Resume Trade Talks in Geneva This Week","Diplomatic talks between the two largest economies have resumed.","https://apnews.com/us-china-talks","associated-press",7),
        # Event 7: Climate - COP summit (cluster of 2)
        ("COP30 Climate Summit: World Leaders Pledge New Emissions Targets","Global leaders at COP30 announced ambitious new climate goals.","https://theguardian.com/environment/cop30","the-guardian-uk",8),
        ("COP30 Climate Summit: World Leaders Pledge Emissions Targets","Nearly 200 nations agreed to stricter targets.","https://bbc.com/news/science/cop30","bbc-news",9),
        # Event 8: Health - New vaccine (cluster of 2)
        ("FDA Approves New mRNA Vaccine Targeting Multiple Variants","FDA approved a new generation mRNA vaccine.","https://apnews.com/health/vaccine","associated-press",10),
        ("FDA Approves New mRNA Vaccine for Multiple Variants","New vaccine provides broad protection.","https://nbcnews.com/health/vaccine","nbc-news",11),
        # Event 9: Cybersecurity breach (standalone)
        ("Major Cybersecurity Breach Affects Millions of Users Worldwide","A sophisticated cyberattack compromised user data.","https://reuters.com/tech/cyber-breach","reuters",12),
        # Event 10: Energy - Oil prices (cluster of 2)
        ("OPEC Plus Agrees to Cut Oil Production, Sending Prices Higher","OPEC agreed to reduce oil output by 1.5m bpd.","https://bloomberg.com/markets/opec-cut","bloomberg",5),
        ("OPEC Plus Agrees to Cut Oil Production, Prices Surge","Crude oil prices jumped after OPEC Plus cut.","https://reuters.com/markets/oil-opec","reuters",6),
        # Event 11: Economy - GDP (cluster of 2)
        ("US GDP Growth Exceeds Expectations in Second Quarter","US economy grew at 3.2 percent in Q2.","https://reuters.com/markets/us-gdp","reuters",14),
        ("US GDP Growth Exceeds Expectations, Economy Expands","New GDP data shows economy expanding at robust pace.","https://apnews.com/economy/gdp","associated-press",15),
        # Event 12: Health - WHO emergency (2 arts - 1 deduped)
        ("WHO Declares End to Global Health Emergency After Three Years","The WHO declared the global health emergency over.","https://bbc.com/news/health/who-emergency","bbc-news",18),
        ("WHO Declares End to Global Health Emergency After Three","WHO announced the end of the global health emergency.","https://cnn.com/health/who-emergency","cnn",19),
        # Event 13: Space (standalone)
        ("NASA Artemis III Successfully Lands Astronauts on Lunar Surface","NASA landed astronauts near the lunar south pole.","https://bbc.com/news/science/artemis","bbc-news",10),
        # Event 14: Entertainment - low weight (standalone)
        ("Blockbuster Movie Breaks Opening Weekend Box Office Records","The sequel shattered box office records.","https://variety.com/movie-records","entertainment-weekly",7),
        # Event 15: Sports - low weight (standalone)
        ("World Cup 2026: Host Nation Advances to Quarterfinals","The host nation secured their spot in the quarterfinals.","https://espn.com/worldcup2026","fox-sports",12),
        # Event 16: Weather (standalone)
        ("Extreme Heatwave Sweeps Across Europe, Records Broken","Temperatures shattered records as a heatwave continues.","https://bbc.com/news/weather/europe-heatwave","bbc-news",14),
        # Event 17: Economy - Recession fears (2 arts - 1 deduped)
        ("Recession Fears Loom as Consumer Spending Slows Sharply","Consumer spending shows a sharp slowdown.","https://ft.com/economy/recession-fears","financial-times",16),
        ("Recession Fears Loom as Consumer Spending Slows","Consumer spending shows a significant slowdown.","https://bloomberg.com/economy/recession","bloomberg",17),
    ]


    source_map = {
        "reuters": "reuters",
        "bbc-news": "bbc-news",
        "cnn": "cnn",
        "associated-press": "associated-press",
        "bloomberg": "bloomberg",
        "the-verge": "the-verge",
        "the-washington-post": "the-washington-post",
        "politico": "politico",
        "the-hill": "the-hill",
        "financial-times": "financial-times",
        "al-jazeera-english": "al-jazeera-english",
        "nbc-news": "nbc-news",
        "the-guardian-uk": "the-guardian-uk",
        "fox-sports": "fox-sports",
        "entertainment-weekly": "entertainment-weekly",
    }

    articles = []
    for title, desc, url, src_key, hrs_ago in raw:
        ts = (now - timedelta(hours=hrs_ago)).isoformat()
        src_id = source_map.get(src_key, "unknown")
        articles.append({
            "title": title,
            "description": desc,
            "url": url,
            "source": src_id,
            "published_at": ts,
            "language": "en",
            "country": "US",
            "raw_provider": "mock",
        })

    return articles


def fetch_all_articles(config, deadline=None):
    if deadline and time.time() > deadline:
        logger.info("  Deadline reached before fetch; returning")
        return []
    """Fetch articles from all enabled providers, accumulating results.

    Always tries every provider sequentially so that a missing API key
    or a single provider failure does not block results.  Logs the
    contribution of each provider clearly.
    """
    articles = []

    logger.info("--- Checking NewsAPI ---")
    newsapi_arts = fetch_newsapi(config, deadline=deadline)
    cnt = len(newsapi_arts)
    if cnt == 0 and not os.environ.get("NEWSAPI_KEY"):
        logger.info("  NewsAPI skipped: missing NEWSAPI_KEY")
    elif cnt == 0:
        logger.info("  NewsAPI returned 0 articles (unavailable or error)")
    else:
        logger.info("  NewsAPI fetched %d articles", cnt)
    articles.extend(newsapi_arts)

    logger.info("--- Checking GDELT DOC 2.0 ---")
    gdelt_arts = fetch_gdelt(config, deadline=deadline)
    cnt = len(gdelt_arts)
    if cnt > 0:
        logger.info("  GDELT fetched %d articles", cnt)
    else:
        logger.info("  GDELT returned 0 articles (unavailable or error)")
    articles.extend(gdelt_arts)

    logger.info("--- Checking RSS feeds ---")
    rss_arts = fetch_rss(config, deadline=deadline)
    cnt = len(rss_arts)
    if cnt > 0:
        logger.info("  RSS fetched %d articles", cnt)
    else:
        logger.info("  RSS returned 0 articles (unavailable or error)")
    articles.extend(rss_arts)

    logger.info("Total before dedup: %d articles (from all providers)", len(articles))
    return articles


def run_pipeline(config, output_dir=None, dry_run=False, deadline=None):
    """Run the full news ranking pipeline.

    Returns the number of top articles exported.
    When dry_run is True, uses mock data and skips external HTTP calls.
    """
    top_n = config.get("output", {}).get("top_n", 20)
    dedup_threshold = config.get("deduplication", {}).get("similarity_threshold", 85)
    cluster_threshold = config.get("deduplication", {}).get("cluster_threshold", 75)
    out_dir = output_dir or config.get("output", {}).get("dir", "outputs")

    logger.info("=" * 50)
    logger.info("Stage 1: Fetching articles")
    if dry_run:
        logger.info("  DRY-RUN mode -- using mock articles (no external calls)")
        raw_articles = generate_mock_articles()
        logger.info("  Generated %d mock articles", len(raw_articles))
    else:
        raw_articles = fetch_all_articles(config, deadline=deadline)

    raw_articles = filter_recent_articles(raw_articles, hours=24)
    raw_articles = filter_low_value_articles(raw_articles)
    if not raw_articles:
        logger.error("No articles fetched from any provider -- nothing to process")
        notify_error("No articles fetched from any provider", config)
        return (0, "FAIL")

    logger.info("Total before dedup: %d", len(raw_articles))

    logger.info("Stage 2: Deduplicating (threshold=%d)", dedup_threshold)
    deduped = deduplicate(raw_articles, threshold=dedup_threshold)
    logger.info("Total after dedup: %d (removed %d duplicates)",
                len(deduped), len(raw_articles) - len(deduped))

    if not deduped:
        logger.warning("All articles were duplicates -- nothing to rank")
        return (0, "FAIL")

    logger.info("Stage 3: Clustering by event similarity")
    events = cluster_events(deduped, threshold=cluster_threshold)

    logger.info("Stage 4: Ranking by hot_score")
    ranked = rank_events(events, config, top_n=top_n)
    logger.info("Final top %d:", len(ranked))
    for i, art in enumerate(ranked, 1):
        logger.info("  #%d [%.2f] %s (%s)",
                    i, art.get("hot_score", 0),
                    art.get("title", "")[:60],
                    art.get("source", ""))

    if not ranked:
        logger.warning("No articles made it through ranking")
        return (0, "FAIL")

    logger.info("Stage 5: Exporting top %d articles", len(ranked))
    warnings, quality = _compute_warnings(raw_articles, ranked)
    export_all(ranked, out_dir, warnings=warnings)

    logger.info("Stage 6: Notification")
    notify(ranked, config)

    return len(ranked), quality


def _compute_warnings(raw_articles, ranked_events):
    warnings = []
    quality = "PASS"
    all_sources = set()
    for art in raw_articles:
        s = art.get("source", "")
        if s:
            all_sources.add(s)
    providers = set(a.get("raw_provider", "") for a in raw_articles if a.get("raw_provider") not in ("mock", ""))
    if providers == {"rss"}:
        warnings.append("RSS-only result; not a reliable global heat ranking.")
        quality = "WARN"
    elif not (providers & {"newsapi", "gdelt"}):
        quality = "WARN"
    if len(all_sources) < 5:
        warnings.append("Low source diversity (%d sources)." % len(all_sources))
        quality = "WARN"
    if ranked_events:
        all_cc = [e.get("cluster_count", 1) for e in ranked_events]
        if all(c == 1 for c in all_cc):
            warnings.append("No cross-source clustering detected.")
            quality = "WARN"
    if ranked_events and len(ranked_events) < 20:
        warnings.append("Only %d qualified events found." % len(ranked_events))
    if not ranked_events:
        quality = "FAIL"
    return warnings, quality


def diagnose_sources(config: dict) -> int:
    """Diagnose data sources without running dedup/ranking/export.

    This deliberately performs only small source checks:
      - NewsAPI: one top-headlines request if NEWSAPI_KEY is present
      - GDELT: one maxrecords=1 request
      - RSS: one request per enabled feed, parse entry count
    """
    logger.info("=" * 50)
    logger.info("Source diagnostics started")

    session = create_session(config)
    timeout = get_timeout(config, default=(5, 12))
    failures = 0

    # 1. NewsAPI
    newsapi_cfg = config.get("sources", {}).get("newsapi", {})
    if not newsapi_cfg.get("enabled", True):
        logger.info("NewsAPI: SKIP disabled in config")
    else:
        api_key = os.getenv("NEWSAPI_KEY")
        if not api_key:
            logger.info("NewsAPI: SKIP missing NEWSAPI_KEY")
        else:
            sources = newsapi_cfg.get("sources", []) or ["bbc-news"]
            probe_source = sources[0]
            url = "https://newsapi.org/v2/top-headlines"
            params = {"apiKey": api_key, "sources": probe_source, "pageSize": 1}
            try:
                resp = session.get(url, params=params, timeout=timeout)
                status = resp.status_code
                if status == 200:
                    try:
                        data = resp.json()
                    except ValueError:
                        data = {}
                    count = len(data.get("articles", [])) if isinstance(data, dict) else 0
                    logger.info("NewsAPI: SUCCESS status=200 source=%s articles=%d", probe_source, count)
                else:
                    logger.warning("NewsAPI: FAIL status=%s source=%s", status, probe_source)
                    failures += 1
            except requests.exceptions.RequestException as e:
                logger.warning("NewsAPI: FAIL %s", type(e).__name__)
                failures += 1

    # 2. GDELT
    gdelt_cfg = config.get("sources", {}).get("gdelt", {})
    if not gdelt_cfg.get("enabled", True):
        logger.info("GDELT: SKIP disabled in config")
    else:
        params = {
            "mode": "artlist",
            "format": "json",
            "maxrecords": 1,
            "timespan": "24h",
            "sort": "DateDesc",
        }
        try:
            resp = session.get("https://api.gdeltproject.org/api/v2/doc/doc", params=params, timeout=timeout)
            status = resp.status_code
            if status == 200:
                logger.info("GDELT: SUCCESS status=200")
            else:
                logger.warning("GDELT: FAIL status=%s", status)
                failures += 1
        except requests.exceptions.RequestException as e:
            logger.warning("GDELT: FAIL %s", type(e).__name__)
            failures += 1

    # 3. RSS
    rss_cfg = config.get("sources", {}).get("rss", {})
    if not rss_cfg.get("enabled", True):
        logger.info("RSS: SKIP disabled in config")
    else:
        feeds = [_normalise_feed_config(f) for f in rss_cfg.get("feeds", [])]
        feeds = [f for f in feeds if f.get("enabled", True) and f.get("url")]
        ok = 0
        total_articles = 0
        logger.info("RSS: checking %d enabled feeds", len(feeds))
        for feed in feeds:
            name = feed.get("name") or feed.get("source") or feed.get("url")
            url = feed.get("url")
            domain = urlparse(url).netloc
            try:
                resp = session.get(
                    url,
                    timeout=timeout,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; GlobalNewsRanker/1.0)"},
                )
                status = resp.status_code
                if status != 200:
                    logger.warning("RSS: FAIL status=%s name=%s domain=%s", status, name, domain)
                    failures += 1
                    continue
                import feedparser
                parsed = feedparser.parse(resp.content)
                entries = len(parsed.entries or [])
                if parsed.bozo and entries == 0:
                    logger.warning("RSS: FAIL parse name=%s domain=%s", name, domain)
                    failures += 1
                    continue
                ok += 1
                total_articles += entries
                logger.info("RSS: SUCCESS name=%s domain=%s entries=%d", name, domain, entries)
            except requests.exceptions.RequestException as e:
                logger.warning("RSS: FAIL name=%s domain=%s error=%s", name, domain, type(e).__name__)
                failures += 1

        logger.info("RSS: SUMMARY success=%d/%d entries=%d", ok, len(feeds), total_articles)

    logger.info("Source diagnostics finished; failures=%d", failures)
    return failures

def main() -> None:
    print("Global News Ranker starting...")

    args = parse_args()

    load_dotenv()

    config_path = os.environ.get("CONFIG_PATH", "config.yaml")
    output_dir = os.environ.get("OUTPUT_DIR", "outputs")

    config = load_config(config_path)

    pipeline_timeout = (
        config.get("network", {}).get("pipeline_timeout")
        or config.get("pipeline_timeout")
        or 90
    )

    try:
        pipeline_timeout = int(pipeline_timeout)
    except (TypeError, ValueError):
        pipeline_timeout = 90

    setup_logging(config)

    logger.info(
        "Global News Ranker started at %s",
        datetime.now(timezone.utc).isoformat(),
    )
    logger.info("Pipeline timeout: %ss", pipeline_timeout)
    logger.info("Config: %s", config_path)
    logger.info("=" * 50)

    if args.diagnose_sources:
        failures = diagnose_sources(config)
        print(f"Diagnostics finished. failures={failures}")
        return

    deadline = time.time() + pipeline_timeout

    result = run_pipeline(
        config,
        output_dir=output_dir,
        dry_run=args.dry_run,
        deadline=deadline,
    )

    if isinstance(result, tuple):
        exported_count, quality = result
    else:
        exported_count = int(result)
        quality = "WARN" if exported_count else "FAIL"

    logger.info(
        "Pipeline finished -- %d events exported; quality=%s",
        exported_count,
        quality,
    )

    print(
        f"Done. {exported_count} qualified events exported. Quality: {quality}"
    )


if __name__ == "__main__":
    main()
