from __future__ import annotations

"""Deduplicate and cluster articles using rapidfuzz title similarity.

Clustering improvements:
  - normalize_title_for_clustering(): removes stop words, normalizes synonyms
  - token_set_ratio(): focuses on common word sets for better event matching
  - related_sources / related_titles added to each article after clustering
"""
import logging

try:
    from rapidfuzz import fuzz as _fuzz
    _HAVE_RAPIDFUZZ = True
except ImportError:
    _HAVE_RAPIDFUZZ = False
    import difflib

    class _FuzzFallback:
        @staticmethod
        def token_sort_ratio(s1: str, s2: str) -> float:
            """Fallback using difflib SequenceMatcher on sorted tokens."""
            tokens1 = sorted(s1.lower().split())
            tokens2 = sorted(s2.lower().split())
            matcher = difflib.SequenceMatcher(None, tokens1, tokens2)
            return round(matcher.ratio() * 100, 2)

        @staticmethod
        def token_set_ratio(s1: str, s2: str) -> float:
            """Token set ratio: focuses on common word sets.

            Finds the intersection of tokens, then scores the best match
            among (intersection+diff1, intersection+diff2, full sets).
            """
            tokens1 = set(s1.lower().split())
            tokens2 = set(s2.lower().split())

            intersection = sorted(tokens1 & tokens2)
            diff1 = sorted(tokens1 - tokens2)
            diff2 = sorted(tokens2 - tokens1)

            if not intersection:
                # No common words — fall back to sort ratio
                ts1 = sorted(s1.lower().split())
                ts2 = sorted(s2.lower().split())
                matcher = difflib.SequenceMatcher(None, ts1, ts2)
                return round(matcher.ratio() * 100, 2)

            def _ratio(a, b):
                return difflib.SequenceMatcher(None, a, b).ratio()

            r1 = _ratio(intersection, intersection + diff1)
            r2 = _ratio(intersection, intersection + diff2)
            r3 = _ratio(intersection + diff1, intersection + diff2)

            return round(max(r1, r2, r3) * 100, 2)

    _fuzz = _FuzzFallback()

logger = logging.getLogger(__name__)

# Words removed before clustering (low-value / overly common)
STOP_WORDS: set = {
    "a", "an", "the", "in", "on", "at", "to", "for", "of", "with", "and", "or",
    "key", "major", "high", "level", "this", "week", "watch", "latest", "update",
    "breaking", "says", "say", "said", "report", "reports", "new", "after",
    "during", "into", "from", "by", "as", "over", "under", "up", "down",
    "launches", "announces", "unveils", "hits", "slows", "just", "now",
}

# Synonym maps applied before clustering (longer phrases first)
SYNONYMS: dict = {
    "battleground states": "swing states",
    "presidential election": "election",
    "interest rates": "rates",
    "artificial intelligence": "ai",
    "high-level": "",
    "to watch": "",
    "this week": "",
    "sending prices higher": "price surge",
    "unveils": "launches",
    "announces": "launches",
    "hits": "strikes",
    "slows": "slowdown",
    "pledge": "promise",
    "surge": "rise",
}


def normalize_title_for_clustering(title: str) -> str:
    """Normalize a title for cluster comparison.

    1. Lowercase
    2. Apply synonym replacement (multi-word first)
    3. Remove stop words
    """
    t = title.lower()
    # Strip punctuation so "offensive," == "offensive"
    import string as _s
    t = "".join(ch for ch in t if ch.isalnum() or ch.isspace())

    for phrase, replacement in sorted(SYNONYMS.items(), key=lambda x: -len(x[0])):
        if phrase in t:
            t = t.replace(phrase, replacement)
            t = t.strip()

    words = [w for w in t.split() if w not in STOP_WORDS]
    return " ".join(words)


def _token_sort_similarity(t1: str, t2: str) -> float:
    """Return token_sort_ratio (0–100) — used for strict dedup on raw titles."""
    if not t1 or not t2:
        return 0.0
    return _fuzz.token_sort_ratio(t1, t2)


def _token_set_similarity_norm(norm1: str, norm2: str) -> float:
    """Return token_set_ratio on ALREADY-NORMALIZED titles — used for clustering."""
    if not norm1 or not norm2:
        return 0.0
    return _fuzz.token_set_ratio(norm1, norm2)


def deduplicate(articles: list[dict], threshold: int = 85) -> list[dict]:
    """Remove near-duplicate articles by title similarity.

    Uses token_sort_ratio on raw titles (strict).
    Keeps the first occurrence (newest-sorted) and drops later articles
    whose title similarity >= threshold.
    """
    if not articles:
        return []

    sorted_articles = sorted(articles, key=lambda a: a.get("published_at", ""), reverse=True)

    kept: list[dict] = []
    dropped = 0

    for art in sorted_articles:
        t1 = art.get("title", "")
        is_dup = False
        for kept_art in kept:
            t2 = kept_art.get("title", "")
            score = _token_sort_similarity(t1, t2)
            if score >= threshold:
                is_dup = True
                break
        if is_dup:
            dropped += 1
        else:
            kept.append(art)

    logger.info("Deduplication: %d kept, %d dropped (threshold=%d)", len(kept), dropped, threshold)
    return kept


def cluster_events(articles: list[dict], threshold: int = 75) -> list[dict]:
    """Group articles into event clusters.

    Uses title normalization (stop-word removal, synonym mapping) +
    token_set_ratio for better event grouping.

    Each article receives:
      - cluster_id, cluster_count, cluster_count_score
      - related_sources: other sources in the same cluster
      - related_titles: other article titles in the same cluster (max 3)
    """
    n = len(articles)
    if n == 0:
        return []

    # 1. Pre-compute normalized titles
    normalized_titles: list[str] = []
    for art in articles:
        normalized_titles.append(normalize_title_for_clustering(art.get("title", "")))

    logger.debug("Normalized titles: %s", normalized_titles)

    # 2. Union-Find on normalised-token-set similarity
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    comparisons = 0
    for i in range(n):
        if not normalized_titles[i]:
            continue
        for j in range(i + 1, n):
            if not normalized_titles[j]:
                continue
            score = _token_set_similarity_norm(normalized_titles[i], normalized_titles[j])
            comparisons += 1
            if score >= threshold:
                union(i, j)

    logger.debug("Cluster comparisons: %d", comparisons)

    # 3. Count cluster sizes
    cluster_sizes: dict[int, int] = {}
    for i in range(n):
        root = find(i)
        cluster_sizes[root] = cluster_sizes.get(root, 0) + 1

    max_count = max(cluster_sizes.values()) if cluster_sizes else 1

    # 4. Build per-cluster article index
    cluster_groups: dict[int, list[int]] = {}
    for i in range(n):
        root = find(i)
        cluster_groups.setdefault(root, []).append(i)

    events: list[dict] = []
    max_size = 0
    for root, group_indices in cluster_groups.items():
        cluster_articles = [articles[i] for i in group_indices]
        distinct_sources = sorted(set(
            a.get("source", "") for a in cluster_articles if a.get("source")
        ))
        all_titles = [a.get("title", "") for a in cluster_articles]
        size = len(cluster_articles)
        if size > max_size:
            max_size = size

        events.append({
            "articles": cluster_articles,
            "cluster_count": size,
            "distinct_sources": distinct_sources,
            "all_titles": all_titles,
        })

    cluster_distinct = len(events)
    logger.info(
        "Clustering: %d articles into %d event clusters, max cluster size=%d",
        n, cluster_distinct, max_size,
    )

    return events
