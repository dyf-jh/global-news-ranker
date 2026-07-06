from __future__ import annotations
"""Export ranked articles to JSON, CSV, and Markdown."""

import csv
import json
import logging
import os
import re
import shutil
from collections import Counter
from datetime import datetime, timezone
from html import unescape

logger = logging.getLogger(__name__)


# 常见“UTF-8 被 GBK/ANSI 错解”后的乱码修复。不要引入第三方依赖。
_MOJIBAKE_REPLACEMENTS = {
    # Common UTF-8 / Windows mojibake patterns, written with unicode escapes
    # so they survive editor encoding issues.
    "\u9225\u6a9a": "’s",   # 鈥檚
    "\u9225\u6a9b": "’t",
    "\u9225\u6a99": "’r",
    "\u9225\u6a9d": "’v",
    "\u9225\u6a92": "’l",
    "\u9225\u6a93": "’m",
    "\u9225\u6a87": "’d",

    "\u9225\u6e03": "“c",   # 鈥渃
    "\u9225\u6e22": "“t",
    "\u9225\u6e1d": "“m",
    "\u9225\u6e1c": "“l",
    "\u9225\u6e1f": "“o",
    "\u9225\u6e1a": "“s",
    "\u9225\u6e1e": "“n",

    "\u9225\u6de5": "“",
    "\u9225\u6de9": "”",
    "\u9225\u699e": "‘",
    "\u9225\u699f": "’",

    "\u9225\uff1f": "”",    # 鈥？
    "\u9225?": "”",         # 鈥?
    "\u9225": "’",          # 鈥

    "\u94c6": "í",          # 铆
    "\u8c29": "á",          # 谩
    "\u8305": "é",          # 茅
    "\u8d38": "ó",          # 贸
    "\u7164": "ú",          # 煤
    "\u4e48": "ô",          # 么
    "\u8042": " ",          # 聂 / sometimes space-like mojibake
    "\u807d": " ",          # 聽
    "\u62e2": "£",
    "\u5e90": "®",
    "\u6f0f": "©",

    "Ã¡": "á",
    "Ã©": "é",
    "Ã­": "í",
    "Ã³": "ó",
    "Ãº": "ú",
    "Ã±": "ñ",
    "Ã¶": "ö",
    "Ã¼": "ü",
    "Ã–": "Ö",
    "Ãœ": "Ü",
    "Â£": "£",
    "Â©": "©",
    "Â®": "®",
    "Â ": " ",
    "â€™": "’",
    "â€˜": "‘",
    "â€œ": "“",
    "â€": "”",
    "â€“": "–",
    "â€”": "—",
    "â€¦": "…",
}

_BAD_MARKERS = (
    "鈥",
    "铆",
    "谩",
    "茅",
    "贸",
    "煤",
    "聽",
    "Ã",
    "Â",
    "â€",
    "�",
)

_BLOCK_TAG_RE = re.compile(
    r"</?(p|div|br|li|ul|ol|section|article|blockquote|h[1-6])\b[^>]*>",
    flags=re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1>",
    flags=re.IGNORECASE | re.DOTALL,
)


def _output_path(base_dir: str, filename: str) -> str:
    """Ensure the output directory exists and return the full path."""
    os.makedirs(base_dir, exist_ok=True)
    return os.path.join(base_dir, filename)


def _badness(text: str) -> int:
    """Score likely mojibake. Lower is better."""
    return sum(text.count(marker) for marker in _BAD_MARKERS) + text.count("\ufffd") * 5


def _fix_mojibake(value: str) -> str:
    """Repair common mojibake without external libraries."""
    if not value:
        return ""

    text = str(value)

    # Context-aware fixes first.
    text = text.replace("Europe live 鈥?latest updates", "Europe live – latest updates")
    text = text.replace("Europe live 鈥？latest updates", "Europe live – latest updates")
    text = text.replace("鈥?which", "” which")
    text = text.replace("鈥？which", "” which")

    for bad, good in _MOJIBAKE_REPLACEMENTS.items():
        text = text.replace(bad, good)

    # Second pass for fragments produced after the first pass.
    for bad, good in _MOJIBAKE_REPLACEMENTS.items():
        text = text.replace(bad, good)

    text = text.replace("Continue reading...", "")
    text = text.replace("Continue reading…", "")

    return text


def _strip_html(value: str) -> str:
    """Remove HTML tags while preserving readable spacing."""
    if not value:
        return ""

    text = unescape(str(value))
    text = _SCRIPT_STYLE_RE.sub(" ", text)
    text = _BLOCK_TAG_RE.sub(" ", text)
    text = _TAG_RE.sub(" ", text)
    text = unescape(text)
    return text


def _collapse_spaces(value: str) -> str:
    """Collapse whitespace into one readable line."""
    text = str(value).replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _truncate(value: str, max_len: int | None = None) -> str:
    if not max_len or len(value) <= max_len:
        return value
    return value[: max_len - 1].rstrip() + "…"


def _clean_text(value, max_len: int | None = None) -> str:
    """Clean text for JSON/CSV/Markdown export."""
    if value is None:
        return ""

    text = str(value)

    # Basic cleaning pipeline.
    text = _fix_mojibake(text)
    text = _strip_html(text)
    text = _fix_mojibake(text)
    text = _collapse_spaces(text)

    # Final hard fallback for common RSS mojibake.
    # Use an ordered list, not dict, so longer bad patterns are replaced first.
    replacements = [
        # Full mojibake pairs: 鈥檚 / 鈥榙 / 鈥?
        ("\u9225\u6a9a", "\u2019s"),   # 鈥檚 -> ’s
        ("\u9225\u6a9b", "\u2019t"),   # 鈥檛 -> ’t
        ("\u9225\u6a99", "\u2019r"),   # 鈥檙 -> ’r
        ("\u9225\u6a9d", "\u2019v"),   # 鈥檝 -> ’v
        ("\u9225\u6a92", "\u2019l"),   # 鈥檒 -> ’l
        ("\u9225\u6a93", "\u2019m"),   # 鈥檓 -> ’m
        ("\u9225\u6a87", "\u2019d"),   # 鈥檇 -> ’d

        ("\u9225\u6999", "\u2018d"),   # 鈥榙 -> ‘d
        ("\u9225\u699a", "\u2018s"),   # 鈥榚 -> ‘s
        ("\u9225\u699f", "\u2019"),    # 鈥榟 -> ’
        ("\u9225\u699e", "\u2018"),    # 鈥榞 -> ‘

        ("\u9225\u6e03", "\u201cc"),   # 鈥渃 -> “c
        ("\u9225\u6e22", "\u201ct"),   # 鈥渢 -> “t
        ("\u9225\u6e1d", "\u201cm"),   # 鈥渝 -> “m
        ("\u9225\u6e1c", "\u201cl"),   # 鈥渜 -> “l
        ("\u9225\u6e1f", "\u201co"),   # 鈥渟 -> “o
        ("\u9225\u6e1a", "\u201cs"),   # 鈥渚 -> “s

        ("\u9225?", "\u201d"),         # 鈥? -> ”
        ("\u9225\uff1f", "\u201d"),    # 鈥？ -> ”

        # Partial mojibake after _fix_mojibake has already converted 鈥 -> ’
        ("\u2019\u6999", "\u2018d"),   # ’榙 -> ‘d
        ("\u2018\u6999", "\u2018d"),   # ‘榙 -> ‘d
        ("'\u6999", "\u2018d"),        # '榙 -> ‘d

        ("\u2019\u6a9a", "\u2019s"),   # ’檚 -> ’s
        ("\u2019\u6a9b", "\u2019t"),   # ’檛 -> ’t
        ("\u2019\u6a99", "\u2019r"),   # ’檙 -> ’r
        ("\u2019\u6a9d", "\u2019v"),   # ’檝 -> ’v
        ("\u2019\u6a92", "\u2019l"),   # ’檒 -> ’l
        ("\u2019\u6a93", "\u2019m"),   # ’檓 -> ’m
        ("\u2019\u6a87", "\u2019d"),   # ’檇 -> ’d

        # Single leftovers
        ("\u9225", "\u2019"),          # 鈥 -> ’
        ("\u6999", "d"),              # 榙 -> d
        ("\u6a9a", "s"),              # 檚 -> s
        ("\u6a9b", "t"),              # 檛 -> t
        ("\u6a99", "r"),              # 檙 -> r
        ("\u6a9d", "v"),              # 檝 -> v
        ("\u6a92", "l"),              # 檒 -> l
        ("\u6a93", "m"),              # 檓 -> m
        ("\u6a87", "d"),              # 檇 -> d

        # Latin accent mojibake
        ("\u94c6", "\u00ed"),         # 铆 -> í
        ("\u8c29", "\u00e1"),         # 谩 -> á
        ("\u8305", "\u00e9"),         # 茅 -> é
        ("\u8d38", "\u00f3"),         # 贸 -> ó
        ("\u7164", "\u00fa"),         # 煤 -> ú
        ("\u4e48", "\u00f4"),         # 么 -> ô
        ("\u807d", " "),              # 聽 -> space

        # RSS boilerplate
        ("Continue reading...", ""),
        ("Continue reading\u2026", ""),
    ]

    for bad, good in replacements:
        text = text.replace(bad, good)

    text = _collapse_spaces(text)
    return _truncate(text, max_len=max_len)

def _md_cell(value) -> str:
    """Escape text for Markdown table cells."""
    return _clean_text(value).replace("|", "\\|")


def _fmt_score(value) -> str:
    try:
        return f"{float(value):.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def _clean_list(values, max_len: int | None = None) -> list[str]:
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    for item in values:
        text = _clean_text(item, max_len=max_len)
        if text:
            cleaned.append(text)
    return cleaned


def _clean_all_articles(items) -> list[dict]:
    """Clean rich cluster data attached to JSON output."""
    if not isinstance(items, list):
        return []

    cleaned_items: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue

        row = dict(item)
        for key in ("title", "description", "summary", "content"):
            if key in row:
                row[key] = _clean_text(row.get(key), max_len=800 if key != "title" else 240)
        cleaned_items.append(row)

    return cleaned_items


def _strip_fields(articles: list[dict]) -> list[dict]:
    """Return articles with only the core fields, plus score fields."""
    rows: list[dict] = []

    for i, a in enumerate(articles):
        rows.append(
            {
                "rank": i + 1,
                "title": _clean_text(a.get("title", ""), max_len=240),
                "description": _clean_text(a.get("description", ""), max_len=700),
                "url": str(a.get("url", "") or "").strip(),
                "source": _clean_text(a.get("source", "")),
                "published_at": str(a.get("published_at", "") or "").strip(),
                "language": _clean_text(a.get("language", "en")),
                "country": _clean_text(a.get("country", "")),
                "raw_provider": _clean_text(a.get("raw_provider", "")),
                "cluster_count": a.get("cluster_count", 1),
                "distinct_sources": _clean_list(a.get("distinct_sources", []), max_len=80),
                "related_titles": _clean_list(a.get("related_titles", []), max_len=240),
                "source_weight": a.get("source_weight", 0),
                "recency_score": a.get("recency_score", 0),
                "topic_weight": a.get("topic_weight", 0),
                "hot_score": a.get("hot_score", 0),
            }
        )

    return rows


def export_json(articles: list[dict], output_dir: str) -> str:
    """Export to latest.json."""
    path = _output_path(output_dir, "latest.json")
    rows = _strip_fields(articles)

    # Attach cleaned rich cluster data for JSON.
    for row, art in zip(rows, articles):
        row["all_articles"] = _clean_all_articles(art.get("all_articles", []))

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(articles),
        "articles": rows,
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info("Exported JSON -> %s (%d articles)", path, len(articles))
    return path


def export_csv(articles: list[dict], output_dir: str) -> str:
    """Export to latest.csv."""
    path = _output_path(output_dir, "latest.csv")
    fields = [
        "rank",
        "title",
        "description",
        "url",
        "source",
        "published_at",
        "language",
        "country",
        "raw_provider",
        "cluster_count",
        "source_weight",
        "recency_score",
        "topic_weight",
        "hot_score",
        "distinct_sources",
        "related_titles",
    ]

    rows = _strip_fields(articles)
    csv_rows: list[dict] = []
    for row in rows:
        r = dict(row)
        r["distinct_sources"] = ", ".join(row.get("distinct_sources", []))
        r["related_titles"] = " | ".join(row.get("related_titles", []))
        csv_rows.append(r)

    # utf-8-sig improves Excel compatibility on Windows.
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(csv_rows)

    logger.info("Exported CSV -> %s (%d articles)", path, len(articles))
    return path


def _build_run_summary(rows: list[dict], warnings=None) -> list[tuple[str, str]]:
    """Build summary metrics for the Markdown report."""
    total = len(rows)

    coverages = []
    sources = []
    providers = []

    for row in rows:
        try:
            coverages.append(int(row.get("cluster_count", 1) or 1))
        except (TypeError, ValueError):
            coverages.append(1)

        source = row.get("source", "") or "unknown"
        provider = row.get("raw_provider", "") or "unknown"

        sources.append(source)
        providers.append(provider)

    source_counter = Counter(sources)
    provider_counter = Counter(providers)

    max_coverage = max(coverages) if coverages else 0
    multi_source_events = sum(1 for c in coverages if c >= 2)
    single_source_events = sum(1 for c in coverages if c <= 1)

    top_source = "N/A"
    if source_counter:
        source, count = source_counter.most_common(1)[0]
        top_source = f"{source}: {count}"

    source_distribution = "N/A"
    if source_counter:
        source_distribution = ", ".join(
            f"{source}: {count}"
            for source, count in source_counter.most_common(8)
        )

    provider_distribution = "N/A"
    if provider_counter:
        provider_distribution = ", ".join(
            f"{provider}: {count}"
            for provider, count in provider_counter.most_common()
        )

    quality = "WARN" if warnings else "PASS"

    return [
        ("Final Events", str(total)),
        ("Max Coverage", str(max_coverage)),
        ("Multi-source Events", str(multi_source_events)),
        ("Single-source Events", str(single_source_events)),
        ("Source Count", str(len(source_counter))),
        ("Top Source", top_source),
        ("Source Distribution", source_distribution),
        ("Provider Distribution", provider_distribution),
        ("Quality", quality),
    ]


def _archive_current_outputs(output_dir: str) -> dict:
    """Copy latest exports into outputs/history/YYYY-MM-DD/."""
    archive_date = datetime.now().strftime("%Y-%m-%d")
    history_dir = os.path.join(output_dir, "history", archive_date)
    os.makedirs(history_dir, exist_ok=True)

    mapping = {
        "latest.json": "top20.json",
        "latest.csv": "top20.csv",
        "latest.md": "top20.md",
    }

    archived = {}

    for src_name, dst_name in mapping.items():
        src_path = os.path.join(output_dir, src_name)
        dst_path = os.path.join(history_dir, dst_name)

        if os.path.exists(src_path):
            shutil.copy2(src_path, dst_path)
            archived[src_name] = dst_path

    if archived:
        logger.info(
            "Archived current outputs -> %s (%d files)",
            history_dir,
            len(archived),
        )

    return archived

def export_markdown(articles: list[dict], output_dir: str, warnings=None) -> str:
    """Export to latest.md as a readable Markdown report."""
    path = _output_path(output_dir, "latest.md")
    rows = _strip_fields(articles)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines: list[str] = []
    lines.append(f"# Global News Ranker - Top {len(rows)} News")
    lines.append("")
    lines.append(f"*Generated at: {generated}*")
    lines.append("")

    if warnings:
        warning_text = " ".join(_clean_text(w) for w in warnings if _clean_text(w))
        if warning_text:
            lines.append("> **Quality Warning:** " + warning_text)
            lines.append("")

    lines.append("## Run Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")

    for metric, value in _build_run_summary(rows, warnings=warnings):
        lines.append(f"| **{_md_cell(metric)}** | {_md_cell(value)} |")

    lines.append("")
    lines.append("---")
    lines.append("")

    for a in rows:
        title = a["title"] or "Untitled"
        source = a["source"]
        score = _fmt_score(a["hot_score"])
        rank = a["rank"]
        cluster = a["cluster_count"]
        desc = a["description"]
        url = a["url"]

        lines.append(f"## {rank}. {title}")
        lines.append("")
        lines.append("| Field | Value |")
        lines.append("|---|---|")
        lines.append(f"| **Source** | {_md_cell(source)} |")
        lines.append(f"| **Hot Score** | {_md_cell(score)} |")
        lines.append(f"| **Coverage** | {_md_cell(cluster)} media outlets |")

        related_srcs = a.get("distinct_sources", [])
        if related_srcs:
            lines.append(f"| **Related Sources** | {_md_cell(', '.join(related_srcs))} |")

        lines.append(f"| **Published** | {_md_cell(a['published_at'])} |")
        lines.append(f"| **Provider** | {_md_cell(a['raw_provider'])} |")
        lines.append("")

        related_titles = a.get("related_titles", [])
        if related_titles:
            lines.append("**Related Stories:**")
            lines.append("")
            for j, rt in enumerate(related_titles, 1):
                lines.append(f"{j}. {_clean_text(rt, max_len=240)}")
            lines.append("")

        if desc:
            lines.append(desc)
            lines.append("")

        if url:
            lines.append(f"[Read full article]({url})")
        else:
            lines.append("*No article URL available.*")

        lines.append("")
        lines.append("---")
        lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    _archive_current_outputs(output_dir)

    logger.info("Exported Markdown -> %s (%d articles)", path, len(articles))
    return path

def export_all(articles: list[dict], output_dir: str, warnings=None) -> dict[str, str]:
    """Export to all three formats. Returns dict of format -> filepath."""
    return {
        "json": export_json(articles, output_dir),
        "csv": export_csv(articles, output_dir),
        "markdown": export_markdown(articles, output_dir, warnings=warnings),
    }