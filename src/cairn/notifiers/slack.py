"""Slack notifier via incoming webhook."""

from __future__ import annotations

import logging

import requests

from ..http import build_session
from .base import Notifier, LEVEL_ERROR, LEVEL_SUCCESS, LEVEL_WARNING

logger = logging.getLogger(__name__)

_EMOJI = {
    LEVEL_SUCCESS: ":white_check_mark:",
    LEVEL_WARNING: ":warning:",
    LEVEL_ERROR: ":x:",
}


class SlackNotifier(Notifier):
    key = "slack"
    display_name = "Slack"

    def setup(self) -> None:
        self.webhook_url = self.config.get("webhook_url", "")
        self.session = build_session()

    def notify(self, title: str, message: str, level: str = "info") -> None:
        if not self.webhook_url:
            return
        if not self.webhook_url.startswith("https://"):
            logger.warning("Slack webhook must be HTTPS; skipping notification")
            return
        emoji = _EMOJI.get(level, ":information_source:")
        payload = {
            "blocks": [
                {"type": "header",
                 "text": {"type": "plain_text", "text": f"{emoji} {title}"[:150]}},
                {"type": "section",
                 "text": {"type": "mrkdwn", "text": message[:3000]}},
            ]
        }
        try:
            resp = self.session.post(self.webhook_url, json=payload, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error("Slack webhook POST failed: %s", e)
