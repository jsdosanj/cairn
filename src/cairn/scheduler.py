"""Install Cairn as a native scheduled job on macOS, Linux, and Windows.

  cairn schedule install --interval 3600    # sync every hour
  cairn schedule status
  cairn schedule uninstall

Backends, by platform:
  * macOS   -> launchd LaunchAgent (~/Library/LaunchAgents/com.cairn.sync.plist)
  * Linux   -> systemd --user service + timer, falling back to cron
  * Windows -> Task Scheduler (schtasks)

The job runs `cairn sync` headlessly with incremental state, so each scheduled
run only writes the devices that actually changed.
"""

from __future__ import annotations

import logging
import os
import platform
import plistlib
import shutil
import subprocess
import sys
from typing import Optional

logger = logging.getLogger(__name__)

LAUNCHD_LABEL = "com.cairn.sync"
SYSTEMD_UNIT = "cairn"
WINDOWS_TASK = "Cairn"


# --- invocation resolution ---------------------------------------------
def resolve_invocation(
    config_path: Optional[str],
    mode: Optional[str],
    command: str = "sync",
) -> list[str]:
    """Build the argv the scheduler should run.

    Prefer an installed `cairn` console binary; fall back to the current Python
    interpreter running the repo entrypoint. Always uses an absolute config path
    so the job works regardless of the scheduler's working directory.

    ``command`` selects the scheduled action: ``sync`` (keep the CMDB current) or
    ``drift`` (the scheduled drift-digest hook — runs read-only and lets the
    configured notifiers deliver a "what's missing/stale/conflicting" digest).
    """
    binary = shutil.which("cairn")
    if binary:
        argv = [binary]
    else:
        entry = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "ghostsync.py",
        )
        argv = [sys.executable, entry]
    if config_path:
        argv += ["-c", os.path.abspath(config_path)]
    argv += [command]
    # --mode only applies to sync; drift is always a read-only fleet pull.
    if mode and command == "sync":
        argv += ["--mode", mode]
    return argv


def _quote(arg: str) -> str:
    return f'"{arg}"' if (" " in arg or "\t" in arg) else arg


def _cmdline(argv: list[str]) -> str:
    return " ".join(_quote(a) for a in argv)


def _interval_minutes(seconds: int) -> int:
    return max(1, seconds // 60)


# --- pure generators (unit-tested) -------------------------------------
def generate_launchd_plist(argv: list[str], interval: int, log_path: str) -> str:
    # Build via plistlib so every value (argv, paths) is XML-escaped; never
    # interpolate untrusted config straight into markup.
    plist = {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": list(argv),
        "StartInterval": interval,
        "RunAtLoad": False,
        "StandardOutPath": log_path,
        "StandardErrorPath": log_path,
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "Nice": 10,
    }
    return plistlib.dumps(plist).decode("utf-8")


def generate_systemd_service(argv: list[str]) -> str:
    return f"""[Unit]
Description=Cairn device asset sync
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart={_cmdline(argv)}
Nice=10
IOSchedulingClass=idle
"""


def generate_systemd_timer(interval: int) -> str:
    return f"""[Unit]
Description=Run Cairn device asset sync on a schedule

[Timer]
OnBootSec=120
OnUnitActiveSec={interval}s
Persistent=true
AccuracySec=1min

[Install]
WantedBy=timers.target
"""


def generate_cron_line(argv: list[str], interval: int) -> str:
    minutes = _interval_minutes(interval)
    if minutes < 60:
        schedule = f"*/{minutes} * * * *"
    else:
        hours = max(1, minutes // 60)
        schedule = f"0 */{hours} * * *"
    return f"{schedule} {_cmdline(argv)}  # {WINDOWS_TASK.lower()}-managed"


def windows_create_argv(argv: list[str], interval: int) -> list[str]:
    minutes = _interval_minutes(interval)
    return [
        "schtasks", "/Create", "/TN", WINDOWS_TASK,
        "/TR", _cmdline(argv), "/SC", "MINUTE", "/MO", str(minutes), "/F",
    ]


# --- install / uninstall / status --------------------------------------
def _launchd_plist_path() -> str:
    return os.path.expanduser(f"~/Library/LaunchAgents/{LAUNCHD_LABEL}.plist")


def _write_private(path: str, content: str) -> None:
    """Write a scheduler artifact, then restrict it to owner-only on POSIX.

    Mirrors SyncState.save(): these files name the config path and invocation,
    so keep them off other local users' radar.
    """
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    if os.name != "nt":
        os.chmod(path, 0o600)


def _log_path() -> str:
    if platform.system() == "Darwin":
        return os.path.expanduser("~/Library/Logs/cairn.log")
    return os.path.expanduser("~/.cairn/cairn.log")


def install(
    interval: int,
    config_path: Optional[str],
    mode: Optional[str],
    command: str = "sync",
) -> str:
    argv = resolve_invocation(config_path, mode, command)
    system = platform.system()
    if system == "Darwin":
        return _install_launchd(argv, interval)
    if system == "Linux":
        return _install_linux(argv, interval)
    if system == "Windows":
        return _install_windows(argv, interval)
    raise RuntimeError(f"Unsupported platform for scheduling: {system}")


def uninstall() -> str:
    system = platform.system()
    if system == "Darwin":
        return _uninstall_launchd()
    if system == "Linux":
        return _uninstall_linux()
    if system == "Windows":
        return _run(["schtasks", "/Delete", "/TN", WINDOWS_TASK, "/F"], "Removed scheduled task.")
    raise RuntimeError(f"Unsupported platform: {system}")


def status() -> str:
    system = platform.system()
    if system == "Darwin":
        path = _launchd_plist_path()
        if not os.path.exists(path):
            return "Not scheduled (no launchd agent installed)."
        out = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
        loaded = LAUNCHD_LABEL in out.stdout
        return f"launchd agent at {path} — {'loaded' if loaded else 'installed but not loaded'}."
    if system == "Linux":
        out = subprocess.run(
            ["systemctl", "--user", "is-active", f"{SYSTEMD_UNIT}.timer"],
            capture_output=True, text=True,
        )
        if out.returncode == 0:
            return f"systemd --user timer {SYSTEMD_UNIT}.timer is {out.stdout.strip()}."
        return "Not scheduled via systemd (check `crontab -l` if you used the cron fallback)."
    if system == "Windows":
        out = subprocess.run(["schtasks", "/Query", "/TN", WINDOWS_TASK],
                             capture_output=True, text=True)
        return out.stdout.strip() if out.returncode == 0 else "Not scheduled (no task found)."
    return f"Unsupported platform: {system}"


def _run(argv: list[str], success_msg: str) -> str:
    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(argv[:2])} failed: {result.stderr.strip() or result.stdout.strip()}")
    return success_msg


def _install_launchd(argv: list[str], interval: int) -> str:
    path = _launchd_plist_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    os.makedirs(os.path.dirname(_log_path()), exist_ok=True)
    _write_private(path, generate_launchd_plist(argv, interval, _log_path()))
    subprocess.run(["launchctl", "unload", path], capture_output=True, text=True)
    _run(["launchctl", "load", "-w", path], "loaded")
    return (f"Installed launchd agent {LAUNCHD_LABEL} (every {interval}s).\n"
            f"  plist: {path}\n  logs:  {_log_path()}")


def _uninstall_launchd() -> str:
    path = _launchd_plist_path()
    if os.path.exists(path):
        subprocess.run(["launchctl", "unload", path], capture_output=True, text=True)
        os.remove(path)
        return f"Removed launchd agent {LAUNCHD_LABEL}."
    return "No launchd agent installed."


def _systemd_dir() -> str:
    return os.path.expanduser("~/.config/systemd/user")


def _systemd_available() -> bool:
    if not shutil.which("systemctl"):
        return False
    probe = subprocess.run(["systemctl", "--user", "show-environment"],
                           capture_output=True, text=True)
    return probe.returncode == 0


def _install_linux(argv: list[str], interval: int) -> str:
    if _systemd_available():
        d = _systemd_dir()
        os.makedirs(d, exist_ok=True)
        _write_private(os.path.join(d, f"{SYSTEMD_UNIT}.service"),
                       generate_systemd_service(argv))
        _write_private(os.path.join(d, f"{SYSTEMD_UNIT}.timer"),
                       generate_systemd_timer(interval))
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, text=True)
        _run(["systemctl", "--user", "enable", "--now", f"{SYSTEMD_UNIT}.timer"], "enabled")
        return (f"Installed systemd --user timer {SYSTEMD_UNIT}.timer (every {interval}s).\n"
                f"  units: {d}/{SYSTEMD_UNIT}.{{service,timer}}\n"
                f"  tip: run `loginctl enable-linger $USER` so it runs while logged out.")
    # Fallback: cron
    line = generate_cron_line(argv, interval)
    existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    current = existing.stdout if existing.returncode == 0 else ""
    kept = "\n".join(l for l in current.splitlines() if "cairn-managed" not in l)
    new_crontab = (kept + "\n" + line + "\n").lstrip("\n")
    proc = subprocess.run(["crontab", "-"], input=new_crontab, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"crontab install failed: {proc.stderr.strip()}")
    return f"systemd not available; installed cron job instead:\n  {line}"


def _uninstall_linux() -> str:
    msgs = []
    if _systemd_available():
        subprocess.run(["systemctl", "--user", "disable", "--now", f"{SYSTEMD_UNIT}.timer"],
                       capture_output=True, text=True)
        for ext in ("service", "timer"):
            p = os.path.join(_systemd_dir(), f"{SYSTEMD_UNIT}.{ext}")
            if os.path.exists(p):
                os.remove(p)
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, text=True)
        msgs.append(f"Removed systemd timer {SYSTEMD_UNIT}.timer.")
    existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if existing.returncode == 0 and "cairn-managed" in existing.stdout:
        kept = "\n".join(l for l in existing.stdout.splitlines() if "cairn-managed" not in l)
        subprocess.run(["crontab", "-"], input=kept + "\n", capture_output=True, text=True)
        msgs.append("Removed cron job.")
    return "\n".join(msgs) or "Nothing scheduled to remove."


def _install_windows(argv: list[str], interval: int) -> str:
    _run(windows_create_argv(argv, interval), "created")
    return f"Installed Windows scheduled task '{WINDOWS_TASK}' (every {_interval_minutes(interval)} min)."
