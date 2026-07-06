# Global News Ranker

AI-powered Global News Intelligence Automation System.

Global News Ranker is a local automation system that collects global news from multiple sources, filters low-value content, deduplicates similar articles, clusters them into news events, ranks the top global stories, generates English and Chinese reports, archives daily outputs, and sends email briefings.

## Features

- Multi-source news collection from NewsAPI and RSS feeds
- Low-value content filtering for sports, entertainment, video-only, and soft-news items
- Article deduplication and event clustering
- Hot-score ranking for global news events
- Top 20 news event export
- English Markdown report generation
- Chinese briefing generation with DeepSeek API
- CSV and JSON structured export
- Daily automation with Windows Task Scheduler
- Email delivery through QQ SMTP
- Local Streamlit dashboard for reports, logs, history, and manual workflow control

## Tech Stack

- Python
- Streamlit
- NewsAPI
- RSS feeds
- DeepSeek API
- QQ SMTP
- PowerShell
- Windows Task Scheduler
- Markdown, CSV, JSON

## Workflow

1. Fetch articles from NewsAPI and RSS feeds.
2. Apply time filtering and low-value content filtering.
3. Deduplicate similar articles.
4. Cluster articles into news events.
5. Rank events by hot score.
6. Export the top 20 events to Markdown, CSV, and JSON.
7. Generate a Chinese briefing with DeepSeek API.
8. Archive daily outputs.
9. Send the report by email.
10. Display reports, logs, history, and task status in a local Streamlit dashboard.

## Project Structure

global-news-ranker/
  main.py
  generate_chinese_brief.py
  send_email_report.py
  app_ui.py
  run_daily.ps1
  run_ui.ps1
  config.yaml
  src/
  docs/
  example_outputs/
  .env.example
  requirements.txt
  README.md
  PROJECT_CASE_STUDY.md

## Local Setup

Install dependencies:

    pip install -r requirements.txt

Create a local environment file:

    copy .env.example .env

Fill in the required API keys and email settings in .env.

Run the pipeline manually:

    python main.py
    python generate_chinese_brief.py
    python send_email_report.py

Start the local dashboard:

    powershell -NoProfile -ExecutionPolicy Bypass -File .\run_ui.ps1

Open:

    http://127.0.0.1:8501

## Automation

The production version runs locally through Windows Task Scheduler at 9:00 AM every day.

The scheduled workflow executes:

- news collection
- filtering
- deduplication
- event clustering
- ranking
- English report generation
- Chinese briefing generation
- historical archiving
- email delivery

## Example Outputs

Sample outputs are stored in example_outputs:

- latest.md: English report
- latest_zh.md: Chinese briefing
- latest.csv: tabular output
- latest.json: structured output

## Screenshots

### Dashboard Overview

![Dashboard Overview](docs/ui_overview.png)

### Chinese Briefing

![Chinese Briefing Overview](docs/chinese_brief_overview.png)

![Chinese Briefing Detail](docs/chinese_brief_detail.png)

### Top 20 Table

![Top 20 Table](docs/top20_table.png)

### Email Delivery

![Email Delivery](docs/email_delivery.png)

## Security

The real .env file is intentionally excluded from this repository.

Do not commit:

- API keys
- SMTP app passwords
- email passwords
- production logs
- full output history
- production zip archives

Use .env.example as the public configuration template.

## Case Study

See PROJECT_CASE_STUDY.md for the project background, architecture, engineering decisions, AI-assisted development process, and future improvements.

## Status

This project has been tested as a working local daily automation system with scheduled execution, report generation, historical archiving, and email delivery.
