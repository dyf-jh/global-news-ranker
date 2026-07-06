from __future__ import annotations
"""Calculate hot_score and rank articles."""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _get_source_weight(source_name: str, weights: dict) -> float:
    """Look up a source's weight, defaulting to config default or 3."""
    source_key = source_name.lower().replace(" ", "-")
    if source_key in weights:
        return float(weights[source_key])
    # Try matching by known aliases
    alias_map = {
        "bbc": "bbc-news",
        "ap": "associated-press",
        "associated press": "associated-press",
        "the associated press": "associated-press",
        "new york times": "new-york-times",
        "the new york times": "new-york-times",
        "wall street journal": "wall-street-journal",
        "the wall street journal": "wall-street-journal",
        "financial times": "financial-times",
        "washington post": "the-washington-post",
        "the washington post": "the-washington-post",
        "guardian": "the-guardian-uk",
        "the guardian": "the-guardian-uk",
        "nbc": "nbc-news",
        "abc": "abc-news",
        "cbs": "cbs-news",
        "fox": "fox-news",
        "al jazeera": "al-jazeera-english",
    }
    if source_key in alias_map:
        mapped = alias_map[source_key]
        if mapped in weights:
            return float(weights[mapped])
    return float(weights.get("default", 3))


def _calc_recency_score(published_at: str, max_hours: int = 24) -> float:
    """Score based on recency. 0h = 10, 24h = 0, linear decay."""
    try:
        pub = datetime.fromisoformat(published_at)
        now = datetime.now(timezone.utc)
        hours_ago = (now - pub).total_seconds() / 3600
        score = max(0.0, 1.0 - hours_ago / max_hours) * 10.0
        return round(score, 2)
    except (ValueError, TypeError):
        return 0.0


def _calc_topic_weight(article: dict, topic_weights: dict) -> float:
    """Find the highest matching topic weight for this article.

    Checks both title and description against keyword lists.
    """
    text = (article.get("title", "") + " " + article.get("description", "")).lower()
    if not text.strip():
        return 1.0

    best_weight = 1.0
    best_topic = None
    for topic, cfg in topic_weights.items():
        keywords = cfg.get("keywords", [])
        weight = cfg.get("weight", 1)
        for kw in keywords:
            if kw.lower() in text:
                if weight > best_weight:
                    best_weight = weight
                    best_topic = topic
                break  # one keyword hit is enough per topic

    if best_topic:
        logger.debug("Topic match: '%s' -> weight=%.1f for '%s'", best_topic, best_weight, article.get("title", "")[:60])
    return best_weight


def calculate_hot_score(article: dict, config: dict) -> float:
    """Calculate hot_score for a single article.

    hot_score =
        source_weight * 0.35 +
        cluster_count_score * 0.30 +
        recency_score * 0.20 +
        topic_weight * 0.15
    """
    source_weights = config.get("source_weights", {})
    topic_weights_config = config.get("topic_weights", {})
    max_hours = config.get("recency", {}).get("max_hours", 24)

    source_weight = _get_source_weight(article.get("source", ""), source_weights)
    cluster_count_score = float(article.get("cluster_count_score", 1))
    recency_score = _calc_recency_score(article.get("published_at", ""), max_hours)
    topic_weight = _calc_topic_weight(article, topic_weights_config)

    hot_score = (
        source_weight * 0.35
        + cluster_count_score * 0.30
        + recency_score * 0.20
        + topic_weight * 0.15
    )

    article["source_weight"] = source_weight
    article["recency_score"] = recency_score
    article["topic_weight"] = topic_weight
    article["hot_score"] = round(hot_score, 2)

    return round(hot_score, 2)


def rank_articles(articles: list[dict], config: dict, top_n: int = 20) -> list[dict]:
    """Calculate hot_score for all articles, sort descending, return top N."""
    if not articles:
        logger.warning("No articles to rank")
        return []

    for art in articles:
        calculate_hot_score(art, config)

    ranked = sorted(articles, key=lambda a: a.get("hot_score", 0), reverse=True)
    top = ranked[:top_n]

    logger.info(
        "Ranked %d articles; top %d selected. Top score: %.2f, Bottom score: %.2f",
        len(articles), top_n,
        top[0].get("hot_score", 0) if top else 0,
        top[-1].get("hot_score", 0) if top else 0,
    )

    return top
    return top


def select_representative(articles: list[dict], source_weights: dict) -> dict:
    """Select the best article to represent an event cluster.

    Priority:
      1. Highest source_weight
      2. Most recent published_at
      3. Longest title (most complete)
    """
    best = None
    best_key = None
    for art in articles:
        weight = _get_source_weight(art.get("source", ""), source_weights)
        pub = art.get("published_at", "") or ""
        title_len = len(art.get("title", "") or "")
        # negate weight and title_len so higher values sort first
        key = (-weight, pub, -title_len)
        if best_key is None or key < best_key:
            best_key = key
            best = art
    return best or articles[0] if articles else {}


def _calc_quality_adjustment(rep: dict, distinct_count: int) -> float:
    """Apply quality penalties/bonuses after base hot_score.

    Goal:
    - Promote events covered by multiple outlets.
    - Demote single-source weak stories.
    - Strongly demote clear entertainment/celebrity/lifestyle stories.
    """
    title = (rep.get("title", "") or "").lower()
    desc = (rep.get("description", "") or "").lower()
    text = f"{title} {desc}"

    adjustment = 0.0

    # Coverage-based adjustment.
    if distinct_count <= 1:
        adjustment -= 0.85
    elif distinct_count == 2:
        adjustment += 0.15
    elif distinct_count == 3:
        adjustment += 0.45
    elif distinct_count >= 4:
        adjustment += 0.75

    # Serious public-interest topics.
    hard_patterns = [
        "war",
        "attack",
        "killed",
        "death toll",
        "court",
        "supreme court",
        "ebola",
        "virus",
        "government",
        "election",
        "trump",
        "russia",
        "ukraine",
        "iran",
        "israel",
        "gaza",
        "nato",
        "sanctions",
        "google",
        "fine",
        "quake",
        "earthquake",
        "wildfire",
        "separatists",
        "police",
        "bomb",
        "funeral",
        "supreme leader",
    ]

    is_hard_news = any(p in text for p in hard_patterns)

    # Strong soft-news patterns. Do not use broad words like "star".
    strong_soft_patterns = [
        "taylor swift",
        "travis kelce",
        "celebrity wedding",
        "star-studded",
        "red carpet",
        "box office",
        "netflix",
        "hollywood",
        "movie trailer",
        "album",
        "music video",
        "fashion",
        "horoscope",
        "lottery",
    ]

    lifestyle_soft_patterns = [
        "cruise passengers",
        "air con failure",
        "wedding",
        "eurovision",
        "festival",
    ]

    if any(p in text for p in strong_soft_patterns):
        adjustment -= 4.0

    if any(p in text for p in lifestyle_soft_patterns) and not is_hard_news:
        adjustment -= 2.5

    # Demote rolling live pages unless they are strongly multi-source.
    live_patterns = [
        " live",
        "live:",
        "live updates",
        "as it happened",
        "first thing",
    ]
    if any(p in text for p in live_patterns) and distinct_count <= 2:
        adjustment -= 0.75

    if is_hard_news:
        adjustment += 0.25

    return adjustment



def _title_tokens(title):
    """Return normalized tokens for rough duplicate detection."""
    text = (title or "").lower()

    for ch in "'’‘“”\"|:;,.!?()[]{}-/–—":
        text = text.replace(ch, " ")

    stopwords = {
        "the", "and", "for", "with", "from", "into", "after", "before",
        "this", "that", "over", "amid", "will", "says", "say", "said",
        "latest", "live", "news", "update", "updates", "cnn", "bbc",
        "guardian", "independent",
    }

    return {
        t.strip()
        for t in text.split()
        if len(t.strip()) >= 3 and t.strip() not in stopwords
    }


def _title_similarity(a, b):
    """Simple Jaccard title similarity."""
    ta = _title_tokens(a)
    tb = _title_tokens(b)

    if not ta or not tb:
        return 0.0

    return len(ta & tb) / max(1, len(ta | tb))


def _is_near_duplicate(event, selected):
    """Avoid selecting two events that are likely the same story."""
    title = (event.get("title", "") or "").lower()
    desc = (event.get("description", "") or "").lower()
    related_titles = event.get("related_titles", []) or []

    event_text = " ".join(
        [title, desc] + [str(x).lower() for x in related_titles]
    )

    def has_any(text, patterns):
        return any(p in text for p in patterns)

    for item in selected:
        other_title = (item.get("title", "") or "").lower()
        other_desc = (item.get("description", "") or "").lower()
        other_related_titles = item.get("related_titles", []) or []

        other_text = " ".join(
            [other_title, other_desc] + [str(x).lower() for x in other_related_titles]
        )

        # Generic title similarity.
        if _title_similarity(title, other_title) >= 0.42:
            return True

        # Khamenei funeral / mourning duplicate.
        khamenei_terms = [
            "khamenei",
            "supreme leader",
            "ayatollah",
        ]
        funeral_terms = [
            "funeral",
            "mourning",
            "dayslong funeral",
            "six-day funeral",
            "six day funeral",
            "public mourning",
        ]

        if (
            has_any(event_text, khamenei_terms)
            and has_any(other_text, khamenei_terms)
            and has_any(event_text, funeral_terms)
            and has_any(other_text, funeral_terms)
        ):
            return True

        # Trump July 4 / America 250 celebration / speech duplicate.
        trump_terms = [
            "trump",
        ]
        america_250_terms = [
            "250th birthday",
            "america's 250",
            "america’s 250",
            "july 4",
            "july 4th",
            "fourth of july",
            "american exceptionalism",
            "communist menace",
            "communist threat",
            "mount rushmore",
        ]

        if (
            has_any(event_text, trump_terms)
            and has_any(other_text, trump_terms)
            and has_any(event_text, america_250_terms)
            and has_any(other_text, america_250_terms)
        ):
            return True

        # NASA telescope duplicate.
        if (
            "nasa" in event_text
            and "telescope" in event_text
            and "nasa" in other_text
            and "telescope" in other_text
        ):
            return True

        # Strait of Hormuz duplicate.
        if (
            "hormuz" in event_text
            and "hormuz" in other_text
        ):
            return True

        # Vatican excommunication duplicate.
        if (
            "vatican" in event_text
            and "excommunicat" in event_text
            and "vatican" in other_text
            and "excommunicat" in other_text
        ):
            return True

        # Monaco bombing duplicate.
        if (
            "monaco" in event_text
            and "bomb" in event_text
            and "monaco" in other_text
            and "bomb" in other_text
        ):
            return True

    return False

def _is_blocked_low_value_event(event):
    """Block clear entertainment/lifestyle/feature stories even if multi-source."""
    title = (event.get("title", "") or "").lower()
    desc = (event.get("description", "") or "").lower()
    text = f"{title} {desc}"

    blocked_patterns = [
        # Celebrity / entertainment
        "taylor swift",
        "travis kelce",
        "mundial 2026",
        "mundial",
        "8vos",
        "colombia va en serio",
        "la sele",

        # Celebrity / personality soft news
        "karlie kloss",
        "trump family ties",
        "dinner table as a democrat",
        "reveals what it's like",

        # Sports match / tournament items
        "cristiano ronaldo",
        "var denies",
        "game-tying goal",
        "round of 16",
        "portugal to round of 16",
        "croatia's game",

        # Sports obituary / athlete profile
        "rams legend",
        "leroy irvin",
        "all-pro cornerback",
        "cornerback, dead",
        "dead at 68",
        "star-studded",
        "celebrity",
        "red carpet",

        # Soft sports/personality
        "ronaldo sends message",

        # Lifestyle / service / weak feature
        "walk 30 minutes",
        "cruise passengers",
        "air con failure",
        "real superhero",
        "wwii veterans' stories",
        "young rwandans reflect",
        "progress, pain and hope",
    ]

    return any(p in text for p in blocked_patterns)

def _is_low_priority_single_source(event):
    """Detect low-value single-source items that should not fill Top20 early."""
    coverage = int(event.get("cluster_count", 1) or 1)

    if coverage > 1:
        return False

    title = (event.get("title", "") or "").lower()
    desc = (event.get("description", "") or "").lower()
    text = f"{title} {desc}"

    low_priority_patterns = [
        # Opinion / commentary / columnist pieces
        "mike davis:",
        "opinion:",
        "commentary:",
        "analysis:",
        "dissecting",
        
        # Feature / anniversary / essay-like stories
        "american dream has survived",
        "usa 250",
        "250th birthday",
        "how the american dream",
        "survived - but only just",

        # Local crime / local lawsuit / local incident
        "michigan shopping mall",
        "shopping mall",
        "third injured in shooting",
        "woman whose dog was killed",
        "lapd cops",
        "sues the city",
        "knicks championship",

        # Weak single-source human-interest / lawsuit / local feature
        "dog was killed",
        "celebrated the knicks",

        # Soft sports / celebrity / lifestyle
        "ronaldo sends message",
        "taylor swift",
        "travis kelce",
        "celebrity",
        "star-studded",
        "walk 30 minutes",
        "cruise passengers",
        "air con failure",

        # Football / World Cup / sports content, including non-English variants
        "world cup",
        "mundial 2026",
        "mundial",
        "8vos",
        "colombia va en serio",
        "la sele",
        "ghana",
        "suiza",

        # Local/rolling live pages that are weak as single-source global items
        "first thing",
        "war latest",
        "live:",
        "as it happened",
        "state conference",
        "climb everest",

        # Local crime / local court stories, weak if single-source
        "boy rapists",
        "third teenager charged",
        "left to die from stab wounds",
        "custody sentences by court of appeal",
        "fordingbridge",

        # Domestic politics with weak global relevance if single-source
        "starmer warns burnham",
        "spend less time on diplomacy",
        "nsw labor",
        "state conference",

        # History / anniversary / feature stories
        "anniversary of 1946 massacre",
        "kielce pogrom",
        "young rwandans reflect",
        "progress, pain and hope",
        "wwii veterans",
        "real superhero",
    ]

    if any(p in text for p in low_priority_patterns):
        return True

    return False


def _can_add_event(event, selected, source_counts, single_source_counts, max_per_source, max_single_source_per_source):
    source = event.get("source", "") or "unknown"
    coverage = int(event.get("cluster_count", 1) or 1)

    if source_counts.get(source, 0) >= max_per_source:
        return False

    if coverage <= 1 and single_source_counts.get(source, 0) >= max_single_source_per_source:
        return False

    if _is_near_duplicate(event, selected):
        return False

    return True


def _add_event(event, selected, source_counts, single_source_counts):
    source = event.get("source", "") or "unknown"
    coverage = int(event.get("cluster_count", 1) or 1)

    selected.append(event)
    source_counts[source] = source_counts.get(source, 0) + 1

    if coverage <= 1:
        single_source_counts[source] = single_source_counts.get(source, 0) + 1


def _apply_source_balance(ranked, top_n):
    """Select top events with coverage priority, source balance, and duplicate suppression."""
    selected = []
    source_counts = {}
    single_source_counts = {}

    max_per_source = 5
    max_single_source_per_source = 2

    # Pass 1: take multi-source events first.
    for event in ranked:
        if _is_blocked_low_value_event(event):
            continue

        coverage = int(event.get("cluster_count", 1) or 1)

        if coverage < 2:
            continue

        if not _can_add_event(
            event,
            selected,
            source_counts,
            single_source_counts,
            max_per_source,
            max_single_source_per_source,
        ):
            continue

        _add_event(event, selected, source_counts, single_source_counts)

        if len(selected) >= top_n:
            return selected

    # Pass 2: fill with high-value single-source events.
    for event in ranked:
        if _is_blocked_low_value_event(event):
            continue
            
        coverage = int(event.get("cluster_count", 1) or 1)

        if coverage > 1:
            continue

        if _is_low_priority_single_source(event):
            continue

        if not _can_add_event(
            event,
            selected,
            source_counts,
            single_source_counts,
            max_per_source,
            max_single_source_per_source,
        ):
            continue

        _add_event(event, selected, source_counts, single_source_counts)

        if len(selected) >= top_n:
            return selected

    # Pass 3: if still fewer than top_n, relax source caps but keep duplicate and low-priority filtering.
    for event in ranked:
        if _is_blocked_low_value_event(event):
            continue
            
        if event in selected:
            continue

        if _is_low_priority_single_source(event):
            continue

        if _is_near_duplicate(event, selected):
            continue

        _add_event(event, selected, source_counts, single_source_counts)

        if len(selected) >= top_n:
            return selected

    # Pass 4: last resort fill. This should rarely be used.
    for event in ranked:
        if _is_blocked_low_value_event(event):
            continue
            
        if event in selected:
            continue

        if _is_near_duplicate(event, selected):
            continue

        _add_event(event, selected, source_counts, single_source_counts)

        if len(selected) >= top_n:
            break

    return selected


def rank_events(events: list[dict], config: dict, top_n: int = 20) -> list[dict]:
    """Rank event clusters by hot_score and return top N event-level dicts.

    This version prioritizes:
      1. multi-source coverage,
      2. source diversity,
      3. recency,
      4. topic importance,
    while demoting single-source weak/soft stories.
    """
    source_weights = config.get("source_weights", {})
    topic_weights_config = config.get("topic_weights", {})
    max_hours = config.get("recency", {}).get("max_hours", 24)

    max_distinct = max(
        (len(e.get("distinct_sources", [])) for e in events),
        default=1,
    )

    ranked: list[dict] = []

    for event in events:
        cluster_articles = event.get("articles", [])
        if not cluster_articles:
            continue

        rep = select_representative(cluster_articles, source_weights)
        distinct_sources = event.get("distinct_sources", [])
        distinct_count = len(distinct_sources)

        source_weight = _get_source_weight(rep.get("source", ""), source_weights)
        cluster_count_score = (
            round((distinct_count / max_distinct) * 10, 2)
            if max_distinct > 0 else 0
        )
        recency_score = _calc_recency_score(rep.get("published_at", ""), max_hours)
        topic_weight = _calc_topic_weight(rep, topic_weights_config)

        # Rebalanced formula:
        # - reduce raw source authority,
        # - increase coverage importance,
        # - keep recency meaningful,
        # - keep topic signal as secondary.
        base_score = (
            source_weight * 0.25
            + cluster_count_score * 0.40
            + recency_score * 0.20
            + topic_weight * 0.15
        )

        quality_adjustment = _calc_quality_adjustment(rep, distinct_count)
        hot_score = base_score + quality_adjustment

        related_titles: list[str] = []
        for a in cluster_articles:
            t = a.get("title", "")
            if t and t != rep.get("title"):
                related_titles.append(t)

        event_out = {
            "title": rep.get("title", ""),
            "description": rep.get("description", ""),
            "url": rep.get("url", ""),
            "source": rep.get("source", ""),
            "published_at": rep.get("published_at", ""),
            "language": rep.get("language", "en"),
            "country": rep.get("country", ""),
            "raw_provider": rep.get("raw_provider", ""),
            "cluster_count": distinct_count,
            "distinct_sources": distinct_sources,
            "related_titles": related_titles[:3],
            "all_articles": cluster_articles,
            "source_weight": source_weight,
            "recency_score": recency_score,
            "topic_weight": topic_weight,
            "cluster_count_score": cluster_count_score,
            "quality_adjustment": round(quality_adjustment, 2),
            "hot_score": round(hot_score, 2),
        }
        ranked.append(event_out)

    ranked.sort(key=lambda e: e["hot_score"], reverse=True)
    top = _apply_source_balance(ranked, top_n)

    if len(ranked) < top_n:
        logger.info(
            "Only %d event clusters available (less than requested %d)",
            len(ranked), top_n,
        )

    logger.info(
        "Ranked %d events; top %d selected. Top score: %.2f, Bottom score: %.2f",
        len(ranked), len(top),
        top[0]["hot_score"] if top else 0,
        top[-1]["hot_score"] if top else 0,
    )

    return top
