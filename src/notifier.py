from __future__ import annotations
"""Notification module — placeholder for future extensions.

This module is designed to be extended with notification channels such as:
- Email (SMTP)
- Telegram bot
- Slack webhook
- WeChat bot
- Twitter/X bot

Each notifier should implement a 'send(articles: list[dict], config: dict) -> bool' interface.
"""
import logging

logger = logging.getLogger(__name__)


def notify(articles: list[dict], config: dict) -> bool:
    """Send notification with ranked articles.

    Currently a no-op placeholder. Extend this function or add new modules
    under src/notifiers/ to enable actual delivery.
    """
    if not articles:
        logger.info("No articles to notify about")
        return True

    logger.info(
        "Notification skipped — no notifier configured. "
        "Top article: '%s' (score: %.2f)",
        articles[0].get("title", "")[:60],
        articles[0].get("hot_score", 0),
    )
    return True


def notify_error(message: str, config: dict) -> bool:
    """Send an error notification.

    Placeholder — intended for alerting when the pipeline fails.
    """
    logger.warning("Error notification placeholder: %s", message)
    return True
