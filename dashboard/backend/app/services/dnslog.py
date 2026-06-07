"""Real-time DNS query visibility from the dnsmasq query log.

dnsmasq is configured with ``log-queries`` writing to
``/var/log/dnsmasq/dnsmasq.log``. Each DNS lookup produces a sequence of
lines, e.g.::

    query[A] example.com from 192.168.0.50
    forwarded example.com to 1.1.1.1
    reply example.com is 93.184.216.34

A *blocked* domain (sinkholed via ``address=/domain/0.0.0.0``) instead
produces::

    query[A] ads.example.com from 192.168.0.50
    config ads.example.com is 0.0.0.0

This module tail-reads the log efficiently (the file can be tens of MB),
parses the events, correlates each query with its verdict, and exposes a
filterable feed plus aggregate statistics for the dashboard. It is
read-only — it never mutates dnsmasq state.
"""
from __future__ import annotations

import os
import re
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from ..config import settings

# Jun  7 20:04:46 dnsmasq[164765]: query[A] example.com from 127.0.0.1
_LINE_RE = re.compile(
    r"^(?P<mon>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2})\s+"
    r"dnsmasq\[\d+\]:\s+(?P<body>.*)$"
)
_QUERY_RE = re.compile(r"^query\[(?P<qtype>[A-Z0-9]+)\]\s+(?P<domain>\S+)\s+from\s+(?P<client>\S+)$")
_CONFIG_RE = re.compile(r"^config\s+(?P<domain>\S+)\s+is\s+(?P<value>.+)$")
_REPLY_RE = re.compile(r"^reply\s+(?P<domain>\S+)\s+is\s+(?P<value>.+)$")
_CACHED_RE = re.compile(r"^cached\s+(?P<domain>\S+)\s+is\s+(?P<value>.+)$")
_FWD_RE = re.compile(r"^forwarded\s+(?P<domain>\S+)\s+to\s+\S+$")

_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

# How many bytes to read from the tail of the log per request. dnsmasq lines
# are short (~80 bytes); 4 MB comfortably covers tens of thousands of events
# while keeping parsing fast and memory bounded.
_TAIL_BYTES = 4 * 1024 * 1024


def _parse_ts(mon: str, day: str, hms: str) -> int:
    """Build a millisecond epoch timestamp. dnsmasq logs have no year, so we
    assume the current year and roll back one year if the date is in the
    future (handles a December→January boundary)."""
    now = datetime.now()
    month = _MONTHS.get(mon, now.month)
    hh, mm, ss = (int(x) for x in hms.split(":"))
    year = now.year
    try:
        dt = datetime(year, month, int(day), hh, mm, ss)
    except ValueError:
        return int(now.timestamp() * 1000)
    if dt > now + timedelta(minutes=5):
        dt = dt.replace(year=year - 1)
    return int(dt.timestamp() * 1000)


def _read_tail(path: str, max_bytes: int) -> list[str]:
    if not os.path.isfile(path):
        return []
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        if size > max_bytes:
            f.seek(size - max_bytes)
            f.readline()  # discard partial first line
        data = f.read()
    return data.decode("utf-8", "replace").splitlines()


def _parse_events(lines: Iterable[str]) -> list[dict[str, Any]]:
    """Correlate query lines with their verdict.

    A query is *blocked* when followed by ``config <domain> is 0.0.0.0``;
    otherwise (forwarded / cached / reply with a real answer) it is
    *allowed*. Verdict lines carry no client/qtype, so we correlate FIFO per
    domain: each domain keeps a queue of unresolved queries, and the next
    verdict for that domain resolves the oldest one. This stays correct when
    duplicate lookups (e.g. back-to-back A and AAAA) are in flight at once.
    """
    pending: dict[str, deque[dict[str, Any]]] = {}
    events: list[dict[str, Any]] = []

    def finalize(domain: str, status: str, answer: str | None) -> None:
        q = pending.get(domain)
        if not q:
            return
        ev = q.popleft()
        # Once allowed (positive evidence), never downgrade.
        if not (ev["status"] == "allowed" and status != "blocked"):
            ev["status"] = status
        if answer is not None and ev.get("answer") is None:
            ev["answer"] = answer
        events.append(ev)
        if not q:
            pending.pop(domain, None)

    def mark_allowed(domain: str) -> None:
        """Tag the oldest pending query allowed without removing it, so a
        later reply line can still attach the resolved address."""
        q = pending.get(domain)
        if q and q[0]["status"] == "pending":
            q[0]["status"] = "allowed"

    for raw in lines:
        m = _LINE_RE.match(raw)
        if not m:
            continue
        body = m.group("body")

        q = _QUERY_RE.match(body)
        if q:
            domain = q.group("domain").lower()
            pending.setdefault(domain, deque()).append({
                "ts": _parse_ts(m.group("mon"), m.group("day"), m.group("time")),
                "domain": domain,
                "type": q.group("qtype"),
                "client": q.group("client"),
                "status": "pending",
                "answer": None,
            })
            continue

        c = _CONFIG_RE.match(body)
        if c:
            domain = c.group("domain").lower()
            value = c.group("value").strip()
            # Only the sinkhole address 0.0.0.0 is a real content-filter block.
            # NXDOMAIN / NODATA are ordinary "not found" answers (e.g. reverse
            # PTR lookups for private IPs) and must NOT be flagged as blocked.
            if value == "0.0.0.0":
                finalize(domain, "blocked", value)
            else:
                finalize(domain, "allowed", value)
            continue

        matched = False
        for rx in (_REPLY_RE, _CACHED_RE):
            r = rx.match(body)
            if r:
                domain = r.group("domain").lower()
                value = r.group("value").strip()
                status = "blocked" if value == "0.0.0.0" else "allowed"
                finalize(domain, status, value)
                matched = True
                break
        if matched:
            continue

        f = _FWD_RE.match(body)
        if f:
            mark_allowed(f.group("domain").lower())

    # Flush anything still pending (queries near the tail without a verdict).
    for q in pending.values():
        for ev in q:
            if ev["status"] == "pending":
                ev["status"] = "allowed"
            events.append(ev)

    events.sort(key=lambda e: e["ts"])
    return events

    # Flush anything still pending (queries near the tail without a verdict).
    for ev in pending.values():
        if ev["status"] == "pending":
            ev["status"] = "allowed"
        events.append(ev)

    events.sort(key=lambda e: e["ts"])
    return events


def _load(max_bytes: int = _TAIL_BYTES) -> list[dict[str, Any]]:
    return _parse_events(_read_tail(settings.dnsmasq_log_file, max_bytes))


def available() -> bool:
    return os.path.isfile(settings.dnsmasq_log_file)


def query_feed(
    *,
    search: str = "",
    client: str = "",
    status: str = "",
    qtype: str = "",
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    """Return recent DNS query events (newest first) with optional filters."""
    events = _load()
    search = (search or "").strip().lower()
    client = (client or "").strip()
    status = (status or "").strip().lower()
    qtype = (qtype or "").strip().upper()

    filtered = []
    for ev in events:
        if search and search not in ev["domain"]:
            continue
        if client and client != ev["client"]:
            continue
        if status and ev["status"] != status:
            continue
        if qtype and ev["type"] != qtype:
            continue
        filtered.append(ev)

    filtered.reverse()  # newest first
    total = len(filtered)
    page = filtered[offset:offset + limit]
    return {
        "available": True,
        "total": total,
        "limit": limit,
        "offset": offset,
        "events": page,
    }


def stats(top: int = 10) -> dict[str, Any]:
    """Aggregate statistics over the loaded window."""
    events = _load()
    if not events:
        return {
            "available": available(),
            "total": 0, "blocked": 0, "allowed": 0, "block_rate": 0.0,
            "window_start": None, "window_end": None,
            "top_blocked": [], "top_allowed": [], "top_clients": [],
        }

    blocked = sum(1 for e in events if e["status"] == "blocked")
    allowed = len(events) - blocked
    blocked_domains: Counter[str] = Counter()
    allowed_domains: Counter[str] = Counter()
    clients: Counter[str] = Counter()
    for e in events:
        clients[e["client"]] += 1
        if e["status"] == "blocked":
            blocked_domains[e["domain"]] += 1
        else:
            allowed_domains[e["domain"]] += 1

    def _top(counter: Counter[str]) -> list[dict[str, Any]]:
        return [{"key": k, "count": v} for k, v in counter.most_common(top)]

    total = len(events)
    return {
        "available": True,
        "total": total,
        "blocked": blocked,
        "allowed": allowed,
        "block_rate": round(blocked / total * 100, 1) if total else 0.0,
        "window_start": events[0]["ts"],
        "window_end": events[-1]["ts"],
        "top_blocked": _top(blocked_domains),
        "top_allowed": _top(allowed_domains),
        "top_clients": _top(clients),
    }
