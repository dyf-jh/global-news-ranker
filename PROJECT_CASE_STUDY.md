# Project Case Study: Global News Ranker

## Background

This project is a practical AI-assisted automation system for daily global news monitoring.

## Problem

Daily news monitoring is repetitive and noisy. News is scattered across many sources, duplicate stories appear frequently, and low-value content can dominate feeds.

## Solution

Global News Ranker automates the full workflow:

1. Fetch articles from NewsAPI and RSS feeds.
2. Filter old and low-value content.
3. Deduplicate similar articles.
4. Cluster articles into events.
5. Rank the top 20 events.
6. Export Markdown, CSV, and JSON files.
7. Generate a Chinese briefing using DeepSeek API.
8. Archive daily outputs.
9. Send the report by email.
10. Provide a Streamlit dashboard.

## Technical Highlights

- Multi-source news collection
- Proxy-aware HTTP configuration
- Low-value content filtering
- Deduplication and event clustering
- Hot-score ranking
- DeepSeek-powered Chinese briefing generation
- QQ SMTP email delivery
- Windows Task Scheduler automation
- Streamlit dashboard
- UTF-8 logging fixes on Windows

## AI-assisted Development Process

AI was used for requirement breakdown, code generation, debugging, PowerShell scripting, Streamlit UI construction, encoding fixes, and documentation drafting.

Human judgment was used for feature selection, testing, API configuration, workflow validation, news quality review, and credential security.

## Outcome

The project successfully runs as a daily local automation system with scheduled execution, report generation, Chinese briefing generation, historical archiving, email delivery, and dashboard monitoring.

## Future Improvements

- Topic classification
- Daily trend comparison
- Stronger ranking metrics
- Database storage
- Docker deployment
- GitHub Actions checks
- Telegram, Feishu, or WeChat Work delivery
