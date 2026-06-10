"""Notifier contract: post run results to chat/webhook channels."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

LEVEL_INFO = "info"
LEVEL_SUCCESS = "success"
LEVEL_WARNING = "warning"
LEVEL_ERROR = "error"


class Notifier(ABC):
    key: str = "base"
    display_name: str = "Notifier"

    def __init__(self, config: dict):
        self.config = config or {}
        self.setup()

    def setup(self) -> None:
        pass

    @abstractmethod
    def notify(self, title: str, message: str, level: str = LEVEL_INFO) -> None:
        """Best-effort post. Must never raise; log and swallow on failure."""
