"""Connection self-tests for sources and sinks.

Powers `cairn doctor` and the live "Test connection" step in the setup wizard
and web dashboard. Probes are intentionally cheap: one page / one lookup.
"""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass

from .config import enabled_items
from .registry import get_sink_class, get_source_class

logger = logging.getLogger(__name__)

_PROBE_SERIAL = "__cairn_healthcheck__"


@dataclass
class CheckResult:
    section: str   # "sources" | "sinks"
    key: str
    ok: bool
    message: str


def probe_source(source) -> tuple[bool, str]:
    """Pull at most one device. Auth/transport errors surface as failures."""
    try:
        next(itertools.islice(source.fetch_all(), 1), None)
        return True, "reachable"
    except Exception as e:  # noqa: BLE001 - report, don't raise
        return False, str(e)[:200]


def probe_sink(sink) -> tuple[bool, str]:
    """A harmless lookup confirms the URL + token work."""
    try:
        sink.find_asset_by_serial(_PROBE_SERIAL)
        return True, "reachable"
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:200]


def check_config(config: dict) -> list[CheckResult]:
    results: list[CheckResult] = []
    for key, cfg in enabled_items(config, "sources").items():
        try:
            source = get_source_class(key)(cfg)
        except Exception as e:  # noqa: BLE001 - config/init failure
            results.append(CheckResult("sources", key, False, f"config: {str(e)[:180]}"))
            continue
        ok, msg = probe_source(source)
        results.append(CheckResult("sources", key, ok, msg))
    for key, cfg in enabled_items(config, "sinks").items():
        try:
            sink = get_sink_class(key)(cfg)
        except Exception as e:  # noqa: BLE001
            results.append(CheckResult("sinks", key, False, f"config: {str(e)[:180]}"))
            continue
        ok, msg = probe_sink(sink)
        results.append(CheckResult("sinks", key, ok, msg))
    return results
