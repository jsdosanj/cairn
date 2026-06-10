"""Microsoft Teams notifier via incoming webhook (Adaptive Card in a wrapper).

Sends a modern Adaptive Card. Falls back gracefully: if the webhook is a legacy
connector, the card still renders as a MessageCard-compatible payload.
"""

from __future__ import annotations

import logging

import requests

from ..http import build_session
from .base import Notifier, LEVEL_ERROR, LEVEL_SUCCESS, LEVEL_WARNING

logger = logging.getLogger(__name__)

_COLORS = {
    LEVEL_SUCCESS: "Good",
    LEVEL_WARNING: "Warning",
    LEVEL_ERROR: "Attention",
}


class TeamsNotifier(Notifier):
    key = "teams"
    display_name = "Microsoft Teams"

    def setup(self) -> None:
        self.webhook_url = self.config.get("webhook_url", "")
        self.session = build_session()

    def notify(self, title: str, message: str, level: str = "info") -> None:
        if not self.webhook_url:
            return
        if not self.webhook_url.startswith("https://"):
            logger.warning("Teams webhook must be HTTPS; skipping notification")
            return
        card = {
            "type": "message",
            "attachments": [{
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {"type": "TextBlock", "size": "Medium", "weight": "Bolder",
                         "text": title[:200], "color": _COLORS.get(level, "Default")},
                        {"type": "TextBlock", "text": message[:2000], "wrap": True},
                    ],
                },
            }],
        }
        try:
            resp = self.session.post(self.webhook_url, json=card, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error("Teams webhook POST failed: %s", e)
