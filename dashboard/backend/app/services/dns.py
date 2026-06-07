"""DNS management on top of dnsmasq.

Manages two dedicated config files under /etc/dnsmasq.d:
  - mundix-dns-records.conf   : local A/AAAA records via `host-record=name,ip`
  - mundix-dns-resolvers.conf : global upstream resolvers via `server=ip`

Also provides a read-only effective-settings overview (parsed across every
.conf, with the source file for each directive) and best-effort observability
derived from dnsmasq's query log.

All mutations reuse network.config_lock + network._validate_and_reload so they
serialise with zone/reservation changes and trigger a real dnsmasq restart
(SIGHUP does not re-read .conf files).
"""
from __future__ import annotations

import ipaddress
import os
import re
from collections import Counter
from typing import Any

from ..config import settings
from . import network

RECORDS_FILE = "mundix-dns-records.conf"
RESOLVERS_FILE = "mundix-dns-resolvers.conf"
CONTENT_BLOCK_FILE = "mundix-content-block.conf"

_RECORDS_HEADER = "# Mundix360 local DNS records - managed by dashboard\n"
_RESOLVERS_HEADER = "# Mundix360 upstream resolvers - managed by dashboard\n"

# Strict single DNS label / FQDN validation (no commas, spaces, '#', etc.).
_LABEL = r"[a-zA-Z0-9_](?:[a-zA-Z0-9_-]{0,61}[a-zA-Z0-9_])?"
_FQDN_RE = re.compile(rf"^(?=.{{1,253}}$){_LABEL}(?:\.{_LABEL})*$")

_HOST_RECORD_RE = re.compile(r"^host-record=(.+)$")
_SERVER_RE = re.compile(r"^server=(.+)$")


def _path(name: str) -> str:
    return os.path.join(settings.dnsmasq_etc_dir, name)


def _valid_name(name: str) -> bool:
    return bool(name) and bool(_FQDN_RE.match(name))


def _valid_ip(ip: str) -> tuple[bool, int | None]:
    try:
        return True, ipaddress.ip_address(ip).version
    except ValueError:
        return False, None


# ----------------------------------------------------------- local records ---
def list_records() -> list[dict[str, Any]]:
    """Parse managed host-record entries. Form: host-record=name[,alias...],ip"""
    path = _path(RECORDS_FILE)
    out: list[dict[str, Any]] = []
    if not os.path.isfile(path):
        return out
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = _HOST_RECORD_RE.match(line)
            if not m:
                continue
            parts = [p.strip() for p in m.group(1).split(",") if p.strip()]
            if len(parts) < 2:
                continue
            ip = parts[-1]
            names = parts[:-1]
            out.append({
                "id": names[0],
                "name": names[0],
                "aliases": names[1:],
                "ip": ip,
            })
    return out


def _write_records(items: list[dict[str, Any]]) -> None:
    lines = [_RECORDS_HEADER]
    for it in items:
        names = [it["name"], *it.get("aliases", [])]
        lines.append(f"host-record={','.join(names)},{it['ip']}\n")
    network._atomic_write(_path(RECORDS_FILE), "".join(lines))


def _blocked_domains() -> set[str]:
    path = _path(CONTENT_BLOCK_FILE)
    names: set[str] = set()
    if not os.path.isfile(path):
        return names
    with open(path) as f:
        for line in f:
            m = re.match(r"^address=/([^/]+)/", line.strip())
            if m:
                names.add(m.group(1).lower())
    return names


def _validate_record(r: dict[str, Any]) -> None:
    name = (r.get("name") or "").strip().lower()
    if not _valid_name(name):
        raise ValueError(f"invalid DNS name: {r.get('name')!r}")
    for alias in r.get("aliases") or []:
        if not _valid_name(str(alias).strip().lower()):
            raise ValueError(f"invalid alias: {alias!r}")
    ok, _ver = _valid_ip((r.get("ip") or "").strip())
    if not ok:
        raise ValueError(f"invalid IP address: {r.get('ip')!r}")


def save_record(r: dict[str, Any], *, create: bool) -> dict[str, Any]:
    _validate_record(r)
    name = r["name"].strip().lower()
    aliases = [a.strip().lower() for a in (r.get("aliases") or [])]
    ip = r["ip"].strip()
    with network.config_lock:
        # Conflict: a managed record name must not also be sinkholed by the
        # content blocklist (otherwise the operator gets contradictory results).
        blocked = _blocked_domains()
        for n in [name, *aliases]:
            if n in blocked:
                raise ValueError(
                    f"'{n}' is blocked in the content filter — remove the block first"
                )
        items = list_records()
        exists = any(i["name"].lower() == name for i in items)
        if create and exists:
            raise ValueError(f"record already exists: {name}")
        if not create and not exists:
            raise ValueError(f"record not found: {name}")
        prev = items
        items = [i for i in items if i["name"].lower() != name]
        items.append({"name": name, "aliases": aliases, "ip": ip})
        _write_records(items)
        reload = network._validate_and_reload()
        if not reload["ok"]:
            _write_records(prev)
            network._validate_and_reload()
            raise ValueError(f"dnsmasq rejected config: {reload['error']}")
    return {"id": name, "name": name, "aliases": aliases, "ip": ip}


def delete_record(name: str) -> dict[str, Any]:
    name = name.strip().lower()
    with network.config_lock:
        items = list_records()
        prev = items
        items = [i for i in items if i["name"].lower() != name]
        _write_records(items)
        reload = network._validate_and_reload()
        if not reload["ok"]:
            _write_records(prev)
            network._validate_and_reload()
            raise ValueError(f"dnsmasq rejected config: {reload['error']}")
    return {"ok": True, "name": name}


# --------------------------------------------------------- upstream resolvers -
def list_resolvers() -> list[dict[str, Any]]:
    """Managed global upstream resolvers (plain `server=ip`)."""
    path = _path(RESOLVERS_FILE)
    out: list[dict[str, Any]] = []
    if not os.path.isfile(path):
        return out
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = _SERVER_RE.match(line)
            if m and "/" not in m.group(1):
                ip = m.group(1).split("#")[0].strip()
                out.append({"id": ip, "server": ip})
    return out


def _write_resolvers(items: list[str]) -> None:
    lines = [_RESOLVERS_HEADER]
    for ip in items:
        lines.append(f"server={ip}\n")
    network._atomic_write(_path(RESOLVERS_FILE), "".join(lines))


def set_resolvers(servers: list[str]) -> dict[str, Any]:
    cleaned: list[str] = []
    for s in servers:
        s = str(s).strip()
        ok, _ = _valid_ip(s)
        if not ok:
            raise ValueError(f"invalid resolver IP: {s!r}")
        if s not in cleaned:
            cleaned.append(s)
    with network.config_lock:
        prev = [r["server"] for r in list_resolvers()]
        _write_resolvers(cleaned)
        reload = network._validate_and_reload()
        if not reload["ok"]:
            _write_resolvers(prev)
            network._validate_and_reload()
            raise ValueError(f"dnsmasq rejected config: {reload['error']}")
    return {"ok": True, "resolvers": cleaned}


# -------------------------------------------------------- settings overview ---
def settings_overview() -> dict[str, Any]:
    """Read-only effective DNS settings parsed across all .conf files, with the
    source file for each upstream so operators can tell managed vs unmanaged."""
    d = settings.dnsmasq_etc_dir
    cache_size = None
    no_resolv = False
    upstreams: list[dict[str, str]] = []
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".conf"):
                continue
            fpath = os.path.join(d, fn)
            try:
                with open(fpath) as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if line.startswith("cache-size="):
                            cache_size = line.split("=", 1)[1].strip()
                        elif line == "no-resolv":
                            no_resolv = True
                        elif line.startswith("server="):
                            val = line.split("=", 1)[1].strip()
                            scoped = val.startswith("/")
                            upstreams.append({
                                "server": val,
                                "source": fn,
                                "scoped": scoped,
                                "managed": fn == RESOLVERS_FILE,
                            })
            except OSError:
                continue
    return {
        "cache_size": cache_size,
        "no_resolv": no_resolv,
        "upstreams": upstreams,
        "records_count": len(list_records()),
        "resolvers_managed": len(list_resolvers()),
        "blocked_domains": len(_blocked_domains()),
    }


# ------------------------------------------------------------ observability ---
_LOG_QUERY_RE = re.compile(
    r"dnsmasq\[\d+\]:\s+query\[(?P<type>[A-Z0-9]+)\]\s+(?P<domain>\S+)\s+from\s+(?P<client>\S+)"
)
_LOG_BLOCK_RE = re.compile(r"dnsmasq\[\d+\]:\s+config\s+(?P<domain>\S+)\s+is\s+0\.0\.0\.0")
_LOG_TS_RE = re.compile(r"^(\w{3}\s+\d+\s+\d{2}:\d{2}:\d{2})")
_DEFAULT_SCAN_BYTES = 512 * 1024


def _read_tail(path: str, max_bytes: int) -> tuple[list[str], dict[str, Any]]:
    meta: dict[str, Any] = {"available": False, "bytes_scanned": 0, "source": path}
    if not os.path.isfile(path):
        meta["warning"] = "log file not found"
        return [], meta
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            start = max(0, size - max_bytes)
            f.seek(start)
            data = f.read()
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()
        # Discard the first (possibly partial) line unless we read from offset 0.
        if start > 0 and lines:
            lines = lines[1:]
        meta["available"] = True
        meta["bytes_scanned"] = len(data)
        meta["truncated"] = start > 0
        return lines, meta
    except PermissionError:
        meta["warning"] = "permission denied reading dnsmasq log"
        return [], meta
    except OSError as e:
        meta["warning"] = f"could not read log: {e}"
        return [], meta


def _log_path() -> str:
    return "/var/log/dnsmasq/dnsmasq.log"


def query_stats(scan_bytes: int = _DEFAULT_SCAN_BYTES, top: int = 12) -> dict[str, Any]:
    lines, meta = _read_tail(_log_path(), scan_bytes)
    domains: Counter[str] = Counter()
    clients: Counter[str] = Counter()
    types: Counter[str] = Counter()
    blocked: Counter[str] = Counter()
    total = 0
    oldest = newest = None
    for ln in lines:
        ts = _LOG_TS_RE.match(ln)
        if ts:
            if oldest is None:
                oldest = ts.group(1)
            newest = ts.group(1)
        q = _LOG_QUERY_RE.search(ln)
        if q:
            total += 1
            domains[q.group("domain").lower()] += 1
            clients[q.group("client")] += 1
            types[q.group("type")] += 1
            continue
        b = _LOG_BLOCK_RE.search(ln)
        if b:
            blocked[b.group("domain").lower()] += 1
    return {
        "total_queries": total,
        "blocked_total": sum(blocked.values()),
        "unique_domains": len(domains),
        "unique_clients": len(clients),
        "top_domains": [{"domain": d, "count": c} for d, c in domains.most_common(top)],
        "top_clients": [{"client": d, "count": c} for d, c in clients.most_common(top)],
        "top_blocked": [{"domain": d, "count": c} for d, c in blocked.most_common(top)],
        "by_type": [{"type": d, "count": c} for d, c in types.most_common()],
        "window": {"oldest": oldest, "newest": newest, **meta},
    }


def recent_queries(limit: int = 80, scan_bytes: int = _DEFAULT_SCAN_BYTES) -> dict[str, Any]:
    lines, meta = _read_tail(_log_path(), scan_bytes)
    blocked = _blocked_domains()
    out: list[dict[str, Any]] = []
    for ln in lines:
        q = _LOG_QUERY_RE.search(ln)
        if not q:
            continue
        ts = _LOG_TS_RE.match(ln)
        domain = q.group("domain")
        out.append({
            "time": ts.group(1) if ts else None,
            "type": q.group("type"),
            "domain": domain,
            "client": q.group("client"),
            "blocked": domain.lower() in blocked,
        })
    out = out[-limit:]
    out.reverse()
    return {"recent": out, "window": meta}
