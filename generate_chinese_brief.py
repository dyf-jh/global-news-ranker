import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_DIR / "outputs"
LATEST_JSON = OUTPUT_DIR / "latest.json"
LATEST_ZH_MD = OUTPUT_DIR / "latest_zh.md"


def load_env():
    env_path = PROJECT_DIR / ".env"

    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value


def read_latest_articles():
    if not LATEST_JSON.exists():
        raise FileNotFoundError("outputs/latest.json not found. Run python main.py first.")

    data = json.loads(LATEST_JSON.read_text(encoding="utf-8"))

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("articles", "items", "data", "results"):
            if isinstance(data.get(key), list):
                return data[key]

    raise ValueError("Unsupported latest.json structure.")


def slim_article(article):
    return {
        "rank": article.get("rank"),
        "title": article.get("title"),
        "source": article.get("source"),
        "hot_score": article.get("hot_score"),
        "cluster_count": article.get("cluster_count"),
        "distinct_sources": article.get("distinct_sources", []),
        "related_titles": article.get("related_titles", [])[:5],
        "description": article.get("description"),
        "published_at": article.get("published_at"),
        "url": article.get("url"),
    }


def build_prompt(articles):
    slim = [slim_article(a) for a in articles[:20]]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""
你是一名严肃国际新闻编辑。请根据我提供的英文新闻 Top20 数据，生成一份中文新闻简报。

强制要求：
1. 只能依据输入数据，不要编造事实。
2. 中文表达要像正式新闻简报，不要口语化。
3. 不要机械直译英文标题，要概括成中文新闻标题。
4. 每条新闻都要解释“为什么重要”。
5. 信息不足时写“目前信息有限”，不要补充不存在的背景。
6. 保留原文链接。
7. 输出必须是 Markdown。
8. 不要输出解释性前言，直接输出正文。

输出结构必须是：

# 全球热点新闻 Top20 中文简报

*生成时间：{now}*

## 今日总览

用 3-5 条 bullet 概括今天的主要趋势。

## 重点新闻速览

| 排名 | 中文标题 | 类型 | 覆盖度 | 重要性 |
|---:|---|---|---:|---|

列出 20 条。

## 详细简报

### 1. 中文标题

- **原始标题：** ...
- **来源：** ...
- **覆盖度：** ... 家媒体
- **事件概述：** 2-4 句中文。
- **为什么重要：** 1-3 句中文。
- **相关报道：**
  1. ...
  2. ...
- **原文链接：** ...

然后继续 2 到 20。

下面是新闻数据 JSON：

{json.dumps(slim, ensure_ascii=False, indent=2)}
""".strip()


def call_deepseek(prompt):
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    api_base = os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com").rstrip("/")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash").strip()

    if not api_key:
        raise RuntimeError("Missing DEEPSEEK_API_KEY in .env")

    url = api_base + "/chat/completions"

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "你是严肃、准确、克制的中文国际新闻简报编辑。"
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.2,
        "max_tokens": 8000,
        "stream": False
    }

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek HTTP error {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"DeepSeek connection error: {e}")

    data = json.loads(raw)

    try:
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        raise RuntimeError(f"Unexpected DeepSeek response: {data}") from e


def archive_chinese_brief():
    today = datetime.now().strftime("%Y-%m-%d")
    history_dir = OUTPUT_DIR / "history" / today
    history_dir.mkdir(parents=True, exist_ok=True)

    dst = history_dir / "top20_zh.md"
    dst.write_text(LATEST_ZH_MD.read_text(encoding="utf-8-sig"), encoding="utf-8-sig")
    return dst


def main():
    load_env()

    articles = read_latest_articles()

    if not articles:
        raise RuntimeError("No articles found in outputs/latest.json")

    prompt = build_prompt(articles)
    markdown = call_deepseek(prompt)

    if not markdown.startswith("#"):
        markdown = "# 全球热点新闻 Top20 中文简报\n\n" + markdown

    LATEST_ZH_MD.write_text(markdown + "\n", encoding="utf-8-sig")
    archive_path = archive_chinese_brief()

    print(f"Chinese brief exported -> {LATEST_ZH_MD}")
    print(f"Chinese brief archived -> {archive_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Chinese brief failed: {e}", file=sys.stderr)
        sys.exit(1)
