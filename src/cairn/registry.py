"""Plugin registry: map config keys to source/sink/notifier classes.

Lazy imports keep startup fast and let an optional provider's missing extra
dependency stay quiet until that provider is actually enabled. Adding a provider
is one line here plus the module.
"""

from __future__ import annotations

import importlib
from typing import Type

from .sources.base import DeviceSource
from .sinks.base import AssetSink
from .notifiers.base import Notifier

# key -> "module:ClassName" (relative to this package)
_SOURCES: dict[str, str] = {
    "jamf": "cairn.sources.jamf:JamfSource",
    "intune": "cairn.sources.intune:IntuneSource",
    "jumpcloud": "cairn.sources.jumpcloud:JumpCloudSource",
    "crowdstrike": "cairn.sources.crowdstrike:CrowdStrikeSource",
    "sophos": "cairn.sources.sophos:SophosSource",
    "defender": "cairn.sources.defender:DefenderSource",
}

_SINKS: dict[str, str] = {
    "snipeit": "cairn.sinks.snipeit:SnipeITSink",
}

_NOTIFIERS: dict[str, str] = {
    "teams": "cairn.notifiers.teams:TeamsNotifier",
    "slack": "cairn.notifiers.slack:SlackNotifier",
    "webhook": "cairn.notifiers.webhook:WebhookNotifier",
}


def _load(path: str):
    module_name, class_name = path.split(":")
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


def available_sources() -> list[str]:
    return sorted(_SOURCES)


def available_sinks() -> list[str]:
    return sorted(_SINKS)


def available_notifiers() -> list[str]:
    return sorted(_NOTIFIERS)


def get_source_class(key: str) -> Type[DeviceSource]:
    if key not in _SOURCES:
        raise KeyError(
            f"Unknown source '{key}'. Available: {', '.join(available_sources())}"
        )
    return _load(_SOURCES[key])


def get_sink_class(key: str) -> Type[AssetSink]:
    if key not in _SINKS:
        raise KeyError(
            f"Unknown sink '{key}'. Available: {', '.join(available_sinks())}"
        )
    return _load(_SINKS[key])


def get_notifier_class(key: str) -> Type[Notifier]:
    if key not in _NOTIFIERS:
        raise KeyError(
            f"Unknown notifier '{key}'. Available: {', '.join(available_notifiers())}"
        )
    return _load(_NOTIFIERS[key])
