"""Content filtering via DNS sinkhole (dnsmasq address/server directives).

Domains are blocked by writing `address=/domain/` entries (returns 0.0.0.0)
to a dedicated dnsmasq config file, then reloading dnsmasq.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from ..config import settings
from . import network, shell

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


def normalize_domain(domain: str) -> str | None:
    """Canonicalise a user-entered domain. ``address=/dominio/0.0.0.0`` blocks the
    domain *and every subdomain* in dnsmasq, so an explicit wildcard such as
    ``*.sefaz.ma.gov.br`` is equivalent to the bare base domain — accept and strip
    the wildcard prefix instead of rejecting it. Returns the canonical domain, or
    ``None`` when it is genuinely malformed."""
    d = (domain or "").strip().lower().rstrip(".")
    while d.startswith("*."):
        d = d[2:]
    d = d.lstrip(".")
    return d if _DOMAIN_RE.match(d) else None


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
    network._atomic_write(path, "".join(lines))


def add_domain(domain: str, note: str = "") -> dict[str, object]:
    norm = normalize_domain(domain)
    if not norm:
        raise ValueError(f"invalid domain: {domain}")
    domain = norm
    with network.config_lock:
        path = settings.content_blocklist_file
        prev = None
        if os.path.isfile(path):
            with open(path) as f:
                prev = f.read()
        domains = _read_domains()
        domains[domain] = note or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _write(domains)
        reload_result = _validate_and_restart(path, prev)
    return {"ok": True, "domain": domain, "reload": reload_result}


def remove_domain(domain: str) -> dict[str, object]:
    domain = normalize_domain(domain) or domain.strip().lower()
    with network.config_lock:
        path = settings.content_blocklist_file
        prev = None
        if os.path.isfile(path):
            with open(path) as f:
                prev = f.read()
        domains = _read_domains()
        if domain in domains:
            del domains[domain]
            _write(domains)
        reload_result = _validate_and_restart(path, prev)
    return {"ok": True, "domain": domain, "reload": reload_result}


def _validate_and_restart(path: str, prev: str | None) -> dict[str, object]:
    """Validate the generated config and restart dnsmasq (SIGHUP doesn't
    re-read .conf files). Rolls back on failure. Caller holds config_lock."""
    test = shell.run(["dnsmasq", "--test"], timeout=20)
    if not test.ok:
        _restore(path, prev)
        return {"ok": False, "stderr": (test.stderr or test.stdout).strip()}
    res = shell.run(["systemctl", "restart", "dnsmasq"], timeout=60)
    if not res.ok:
        _restore(path, prev)
        shell.run(["systemctl", "restart", "dnsmasq"], timeout=60)
        return {"ok": False, "stderr": res.stderr.strip()}
    return {"ok": True, "stderr": ""}


def _restore(path: str, prev: str | None) -> None:
    if prev is None:
        if os.path.isfile(path):
            os.remove(path)
    else:
        network._atomic_write(path, prev)


def reload_dnsmasq() -> dict[str, object]:
    with network.config_lock:
        test = shell.run(["dnsmasq", "--test"], timeout=20)
        if not test.ok:
            return {"ok": False, "stderr": (test.stderr or test.stdout).strip()}
        res = shell.run(["systemctl", "restart", "dnsmasq"], timeout=60)
        return {"ok": res.ok, "stderr": res.stderr.strip()}
