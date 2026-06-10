"""Generic JSON webhook notifier.

POSTs a plain JSON document so the run can drive any HTTP endpoint (PagerDuty
Events, a custom collector, an automation runner). No vendor assumptions.
"""

from __future__ import annotations

import logging

import requests

from ..http import build_session
from .base import Notifier

logger = logging.getLogger(__name__)


class WebhookNotifier(Notifier):
    key = "webhook"
    display_name = "Generic Webhook"

    def setup(self) -> None:
        self.url = self.config.get("url", "")
        self.session = build_session()
        extra = self.config.get("headers") or {}
        if extra:
            self.session.headers.update(extra)

    def notify(self, title: str, message: str, level: str = "info") -> None:
        if not self.url:
            return
        if not self.url.startswith("https://"):
            logger.warning("Webhook URL must be HTTPS; skipping notification")
            return
        payload = {"title": title, "message": message, "level": level, "source": "cairn"}
        try:
            resp = self.session.post(self.url, json=payload, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error("Webhook POST failed: %s", e)
