"""Local machine fact collection for agent mode (macOS, Windows, Linux).

Used when Cairn runs on an endpoint and only needs to sync the machine it's
running on. In fleet mode this is not used; sources provide the inventory.
"""

from __future__ import annotations

import logging
import platform
import socket
import subprocess
import uuid

from .models import NormalizedDevice

logger = logging.getLogger(__name__)


def _run(args: list[str], timeout: int = 10) -> str:
    try:
        return subprocess.check_output(args, shell=False, timeout=timeout).decode(errors="replace")
    except Exception as e:  # noqa: BLE001 - best effort, never crash collection
        logger.debug("command %s failed: %s", args[0], e)
        return ""


def get_serial() -> str:
    system = platform.system()
    try:
        if system == "Windows":
            # wmic is deprecated on Win11; try PowerShell CIM first, fall back.
            out = _run([
                "powershell", "-NoProfile", "-Command",
                "(Get-CimInstance Win32_BIOS).SerialNumber",
            ])
            serial = out.strip().splitlines()[-1].strip() if out.strip() else ""
            if not serial:
                out = _run(["wmic", "bios", "get", "serialnumber"])
                lines = [l.strip() for l in out.splitlines() if l.strip()]
                serial = lines[1] if len(lines) > 1 else ""
            return serial or "UNKNOWN"
        if system == "Darwin":
            out = _run(["system_profiler", "SPHardwareDataType"])
            for line in out.splitlines():
                if "Serial Number" in line:
                    return line.split(":")[-1].strip()
            return "UNKNOWN"
        # Linux
        for path in ("/sys/class/dmi/id/product_serial", "/sys/class/dmi/id/board_serial"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    val = f.read().strip()
                    if val:
                        return val
            except OSError:
                continue
        out = _run(["dmidecode", "-s", "system-serial-number"])
        return out.strip() or "UNKNOWN"
    except Exception as e:  # noqa: BLE001
        logger.debug("serial lookup failed: %s", e)
        return "UNKNOWN"


def get_mac_address() -> str:
    mac = hex(uuid.getnode()).replace("0x", "").upper().zfill(12)
    return ":".join(mac[i:i + 2] for i in range(0, 12, 2))


def get_logged_in_users() -> str:
    system = platform.system()
    if system == "Windows":
        out = _run(["query", "user"])
    else:
        out = _run(["users"])
    return out.strip() or "UNKNOWN"


def _os_name() -> str:
    system = platform.system()
    return {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}.get(system, system)


def collect_local_device() -> NormalizedDevice:
    return NormalizedDevice(
        serial=get_serial(),
        source="local",
        hostname=socket.gethostname(),
        mac_addresses=[get_mac_address()],
        os_name=_os_name(),
        os_version=platform.version(),
        os_build=platform.release(),
        logged_in_users=get_logged_in_users(),
    )
