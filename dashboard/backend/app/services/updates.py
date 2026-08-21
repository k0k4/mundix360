"""Stable-channel updates (signed APT repo on GitHub Pages, mundix360 pkg only).

The channel serves a plain-text ``/version`` file with the latest stable
version. Checks are operator-triggered from the panel and cached briefly in
memory so repeated clicks do not hammer GitHub Pages.

Applying an update restarts THIS API (the .deb postinst runs the installer
phases, which restart ``mundix-dashboard-api``). The upgrade therefore runs
detached in a transient systemd unit (``systemd-run``): a plain nohup child
would live in the API's cgroup and be killed by ``systemctl restart``
(default ``KillMode=control-group``). State is persisted to
``data/update_state.json`` so the SPA can keep polling across the restart.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from ..config import settings

MANIFEST = os.path.join(settings.base_dir, "installer", "manifest.env")
UPGRADE_SCRIPT = os.path.join(settings.base_dir, "scripts", "ops", "mundix-upgrade.sh")
LOG_FILE = "/var/log/mundix-upgrade.log"
DATA_DIR = os.path.join(settings.base_dir, "dashboard", "backend", "data")
STATE_FILE = os.path.join(DATA_DIR, "update_state.json")
EXIT_FILE = os.path.join(DATA_DIR, "update_exitcode")
UNIT = "mundix-upgrade.service"

CHECK_TIMEOUT = 10.0
CACHE_TTL = 300  # 5 min — checks are manual, but avoid hammering the channel
LOG_TAIL_LINES = 80

_lock = threading.Lock()
_cache: dict[str, Any] = {}


class UpdateInProgress(Exception):
    """Raised when apply is requested while another upgrade is running."""


# ------------------------------------------------------------- versions ------

def current_version() -> str:
    """Read MUNDIX_VERSION from the deployment manifest."""
    try:
        with open(MANIFEST, encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r'^MUNDIX_VERSION="?([^"\n]+)"?', line)
                if m:
                    return m.group(1).strip()
    except OSError:
        pass
    return "desconhecida"


def _ver_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(p) if p.isdigit() else 0 for p in re.split(r"[.\-+]", v.strip()))


def _newer(latest: str, current: str) -> bool:
    """Numeric-tuple compare (1.10.0 > 1.2.0); tie/unknown means no update."""
    if not latest or not current or current == "desconhecida":
        return False
    a, b = _ver_tuple(latest), _ver_tuple(current)
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a > b


# ----------------------------------------------------------------- check -----

def check(force: bool = False) -> dict[str, Any]:
    """Query the channel's /version file. Never raises: an unreachable channel
    yields an ``error`` field (the router maps it to a 502)."""
    now = time.time()
    global _cache
    with _lock:
        if not force and _cache and (now - _cache.get("_ts", 0)) < CACHE_TTL:
            return {k: v for k, v in _cache.items() if k != "_ts"}

    current = current_version()
    checked_at = datetime.now(timezone.utc).isoformat()
    try:
        resp = httpx.get(f"{settings.update_url.rstrip('/')}/version",
                         timeout=CHECK_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        latest = resp.text.strip()
        if not re.fullmatch(r"[0-9][0-9A-Za-z.\-+]*", latest):
            raise ValueError(f"resposta inesperada do canal: {latest[:40]!r}")
        result: dict[str, Any] = {
            "current": current,
            "latest": latest,
            "update_available": _newer(latest, current),
            "checked_at": checked_at,
        }
    except Exception as e:
        result = {
            "current": current,
            "latest": None,
            "update_available": False,
            "checked_at": checked_at,
            "error": f"canal de atualizações inalcançável: {e}",
        }
    with _lock:
        _cache = {**result, "_ts": now}
    return result


def overview() -> dict[str, Any]:
    """Current version + the cached result of the last check (if any)."""
    with _lock:
        last = {k: v for k, v in _cache.items() if k != "_ts"} or None
    return {"current": current_version(), "last_check": last}


# ----------------------------------------------------------------- apply -----

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_state() -> dict[str, Any]:
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _write_state(st: dict[str, Any]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(st, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


def _unit_active() -> bool:
    try:
        return subprocess.run(
            ["systemctl", "is-active", "--quiet", UNIT],
            capture_output=True, timeout=5,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _read_exitcode() -> int | None:
    try:
        with open(EXIT_FILE, encoding="utf-8") as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def _log_tail() -> str:
    try:
        with open(LOG_FILE, encoding="utf-8", errors="replace") as fh:
            return "".join(fh.readlines()[-LOG_TAIL_LINES:])
    except OSError:
        return ""


def apply_async() -> dict[str, Any]:
    """Fire the upgrade detached and return the fresh (running) state."""
    if not os.path.isfile(UPGRADE_SCRIPT):
        raise FileNotFoundError(f"script de upgrade não encontrado: {UPGRADE_SCRIPT}")
    with _lock:
        if status().get("state") == "running":
            raise UpdateInProgress()
        try:
            os.remove(EXIT_FILE)
        except OSError:
            pass
        st = {"state": "running", "started_at": _now(),
              "finished_at": None, "log_tail": ""}
        _write_state(st)
        # Transient unit: survives the API restart that the upgrade itself
        # triggers (a nohup child would be SIGTERMed with the API cgroup).
        # The wrapper records the exit code so status() can settle the state
        # even after the unit is collected by systemd.
        wrapper = f'"{UPGRADE_SCRIPT}" --yes; echo $? > "{EXIT_FILE}"'
        try:
            subprocess.run(
                ["systemd-run", "--unit=mundix-upgrade", "--collect", "--quiet",
                 "--", "/bin/bash", "-c", wrapper],
                check=True, capture_output=True, text=True, timeout=15,
            )
        except Exception as e:
            st.update(state="failed", finished_at=_now(),
                      log_tail=f"falha ao disparar o upgrade: {e}")
            _write_state(st)
            raise
        return st


def status() -> dict[str, Any]:
    """Read the persisted state, reconciling it with the live unit/process."""
    st = _read_state()
    if st.get("state") != "running":
        return st or {"state": "idle"}
    rc = _read_exitcode()
    if rc is not None:
        st["state"] = "success" if rc == 0 else "failed"
        st["finished_at"] = _now()
        st["log_tail"] = _log_tail()
        _write_state(st)
    elif not _unit_active():
        st["state"] = "failed"
        st["finished_at"] = _now()
        st["log_tail"] = _log_tail()
        st["error"] = "processo de upgrade não está mais ativo (interrupção inesperada)"
        _write_state(st)
    else:
        st["log_tail"] = _log_tail()
    return st
