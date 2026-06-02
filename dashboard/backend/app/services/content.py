"""Content filtering via DNS sinkhole (dnsmasq address/server directives).

Domains are blocked by writing `address=/domain/` entries (returns 0.0.0.0)
to a dedicated dnsmasq config file, then reloading dnsmasq.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from ..config import settings
from . import shell

_HEADER = "# Mundix360 content blocklist - managed by dashboard\n"
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-zA-Z0-9_-]{1,63}\.)+[a-zA-Z]{2,}$")
_LINE_RE = re.compile(r"^address=/([^/]+)/0\.0\.0\.0\s*(?:#\s*(.*))?$")


def _ensure_file() -> str:
    path = settings.content_blocklist_file
    if not os.path.isfile(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(_HEADER)
    return path


def validate_domain(domain: str) -> bool:
    return bool(_DOMAIN_RE.match(domain.strip().lower()))


def list_blocked_domains() -> list[dict[str, str]]:
    path = settings.content_blocklist_file
    out: list[dict[str, str]] = []
    if not os.path.isfile(path):
        return out
    with open(path) as f:
        for line in f:
            m = _LINE_RE.match(line.strip())
            if m:
                out.append({"domain": m.group(1), "note": (m.group(2) or "").strip()})
    return out


def _read_domains() -> dict[str, str]:
    return {d["domain"]: d["note"] for d in list_blocked_domains()}


def _write(domains: dict[str, str]) -> None:
    path = _ensure_file()
    lines = [_HEADER]
    for domain in sorted(domains):
        note = domains[domain]
        ts = note or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        lines.append(f"address=/{domain}/0.0.0.0 # {ts}\n")
    with open(path, "w") as f:
        f.writelines(lines)


def add_domain(domain: str, note: str = "") -> dict[str, object]:
    domain = domain.strip().lower()
    if not validate_domain(domain):
        raise ValueError(f"invalid domain: {domain}")
    domains = _read_domains()
    domains[domain] = note or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _write(domains)
    reload_result = reload_dnsmasq()
    return {"ok": True, "domain": domain, "reload": reload_result}


def remove_domain(domain: str) -> dict[str, object]:
    domain = domain.strip().lower()
    domains = _read_domains()
    if domain in domains:
        del domains[domain]
        _write(domains)
    reload_result = reload_dnsmasq()
    return {"ok": True, "domain": domain, "reload": reload_result}


def reload_dnsmasq() -> dict[str, object]:
    res = shell.run(["systemctl", "reload-or-restart", "dnsmasq"], timeout=15)
    return {"ok": res.ok, "stderr": res.stderr.strip()}
