import json
from collections import Counter

with open("outputs/latest.json", "r", encoding="utf-8") as f:
    data = json.load(f)

articles = data.get("articles", [])

print("=" * 80)
print("TOP20 QUALITY DIAGNOSIS")
print("=" * 80)
print("Total:", len(articles))
print()

source_counter = Counter(a.get("source", "") for a in articles)
coverage_counter = Counter(a.get("cluster_count", 1) for a in articles)
provider_counter = Counter(a.get("raw_provider", "") for a in articles)

print("SOURCE DISTRIBUTION")
for source, count in source_counter.most_common():
    print(f"{source}: {count}")
print()

print("COVERAGE DISTRIBUTION")
for coverage, count in sorted(coverage_counter.items(), reverse=True):
    print(f"coverage={coverage}: {count}")
print()

print("PROVIDER DISTRIBUTION")
for provider, count in provider_counter.most_common():
    print(f"{provider}: {count}")
print()

soft_keywords = [
    "taylor swift",
    "travis kelce",
    "wedding",
    "cruise",
    "passengers",
    "air con",
    "celebrity",
    "football",
    "world cup",
    "eurovision",
    "movie",
    "tv",
    "show",
    "festival",
    "fashion",
    "music",
    "sport",
]

print("=" * 80)
print("TOP20 DETAILS")
print("=" * 80)

for a in articles:
    title = a.get("title", "")
    desc = a.get("description", "")
    source = a.get("source", "")
    coverage = a.get("cluster_count", 1)
    score = a.get("hot_score", 0)
    related_sources = a.get("distinct_sources", [])
    provider = a.get("raw_provider", "")

    text = f"{title} {desc}".lower()
    soft_hits = [kw for kw in soft_keywords if kw in text]

    flags = []

    if coverage <= 1:
        flags.append("SINGLE_SOURCE")

    if soft_hits:
        flags.append("SOFT_NEWS:" + ",".join(soft_hits))

    if source in ("bbc-news", "the-guardian-uk"):
        flags.append("DOMINANT_SOURCE")

    print(f"#{a.get('rank')} | score={score} | coverage={coverage} | source={source} | provider={provider}")
    print("TITLE:", title)
    print("RELATED SOURCES:", ", ".join(related_sources))
    print("FLAGS:", " | ".join(flags) if flags else "OK")
    print("-" * 80)