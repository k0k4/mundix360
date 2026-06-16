"""Firewall log visibility.

Surfaces the structured nftables kernel-log events emitted by ``fwmanage`` —
``NFT-INPUT-DROP``, ``NFT-FORWARD-DROP``, ``NFT-SSH-*``, ``MX-RULE <name>`` and
``MX-ZONE <src>><dst>`` — into structured, filterable records so an operator can
answer questions like "did this IP hit this port?", "was the packet blocked?",
"which sources are being dropped the most?".

These prefixes are logged to the kernel ring buffer (``log prefix`` rules), which
journald captures under ``journalctl -k``. We grep the most recent matching lines
(fast: PCRE ``-g`` + ``-n`` tail), parse the standard ``IN= OUT= MAC= SRC= DST=
PROTO= SPT= DPT=`` payload, then apply in-Python filters and aggregations.

No live ``accept`` traffic is logged by design (anti-lockout + low-power Atom), so
this view is focused on *blocked / filtered* events plus any rules the operator
explicitly flagged with ``log=True``.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from . import shell

# Pattern handed to journalctl --grep (PCRE). Matches every Mundix log prefix.
_GREP = r"NFT-|MX-RULE|MX-ZONE"

# journalctl short-iso line:
#   2026-06-16T01:51:50+0000 host kernel: NFT-INPUT-DROP: IN=enp1s0 OUT= ...
_LINE_RE = re.compile(
    r"^(?P<ts>\S+)\s+\S+\s+kernel:\s*(?P<body>.*)$"
)
# Everything up to the first " IN=" / "IN=" is the prefix label.
_BODY_RE = re.compile(r"^(?P<prefix>.*?):?\s*(?P<kv>IN=.*)$", re.DOTALL)
_KV_RE = re.compile(r"(\w+)=([^\s]*)")

# How an MX-ZONE prefix names the zones, e.g. "MX-ZONE lan>dmz".
_MXZONE_RE = re.compile(r"MX-ZONE\s+(?P<src>\S+?)>(?P<dst>\S+)")
_MXRULE_RE = re.compile(r"MX-RULE\s+(?P<name>.+)")


def _classify(prefix: str) -> dict[str, Any]:
    """Map a raw log prefix to a stable action code + human reason (pt-BR)."""
    p = prefix.strip()
    up = p.upper()
    if up.startswith("NFT-INPUT-DROP"):
        return {"action": "drop", "category": "input",
                "reason": "Bloqueio de entrada (destinado ao firewall)"}
    if up.startswith("NFT-FORWARD-DROP"):
        return {"action": "drop", "category": "forward",
                "reason": "Bloqueio de encaminhamento (atravessando o firewall)"}
    if up.startswith("NFT-SSH-DENY"):
        return {"action": "drop", "category": "ssh",
                "reason": "SSH negado (fora da allowlist)"}
    if up.startswith("NFT-SSH-BLOCK"):
        return {"action": "drop", "category": "ssh",
                "reason": "SSH bloqueado (política)"}
    if up.startswith("NFT-SSH-THROTTLE"):
        return {"action": "drop", "category": "ssh",
                "reason": "SSH limitado (rate-limit excedido)"}
    if up.startswith("MX-ZONE"):
        m = _MXZONE_RE.search(p)
        zones = f" {m.group('src')}→{m.group('dst')}" if m else ""
        return {"action": "drop", "category": "zone",
                "reason": f"Bloqueio entre zonas{zones}",
                "zone_src": m.group("src") if m else None,
                "zone_dst": m.group("dst") if m else None}
    if up.startswith("MX-RULE"):
        m = _MXRULE_RE.search(p)
        name = m.group("name").strip() if m else ""
        return {"action": "log", "category": "rule",
                "reason": f"Regra personalizada: {name}" if name else "Regra personalizada",
                "rule": name or None}
    return {"action": "log", "category": "other", "reason": p or "Evento de firewall"}


def _parse_ts(raw: str) -> str | None:
    """Normalise journalctl's short-iso timestamp to RFC3339 (UTC-aware)."""
    s = raw.strip()
    # short-iso emits e.g. 2026-06-16T01:51:50+0000 ; pad the offset colon so
    # fromisoformat accepts it across Python versions.
    m = re.match(r"^(.*?)([+-]\d{2})(\d{2})$", s)
    if m:
        s = f"{m.group(1)}{m.group(2)}:{m.group(3)}"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def parse_line(line: str) -> dict[str, Any] | None:
    """Parse a single journalctl line into a structured firewall event."""
    lm = _LINE_RE.match(line)
    if not lm:
        return None
    bm = _BODY_RE.match(lm.group("body"))
    if not bm:
        return None
    info = _classify(bm.group("prefix"))
    kv = {k.upper(): v for k, v in _KV_RE.findall(bm.group("kv"))}
    if not kv.get("SRC") and not kv.get("DST"):
        return None

    ev: dict[str, Any] = {
        "ts": _parse_ts(lm.group("ts")),
        "action": info["action"],
        "category": info["category"],
        "reason": info["reason"],
        "in_iface": kv.get("IN") or None,
        "out_iface": kv.get("OUT") or None,
        "src": kv.get("SRC") or None,
        "dst": kv.get("DST") or None,
        "proto": (kv.get("PROTO") or "").upper() or None,
        "spt": int(kv["SPT"]) if kv.get("SPT", "").isdigit() else None,
        "dpt": int(kv["DPT"]) if kv.get("DPT", "").isdigit() else None,
        "length": int(kv["LEN"]) if kv.get("LEN", "").isdigit() else None,
        "ttl": int(kv["TTL"]) if kv.get("TTL", "").isdigit() else None,
    }
    # ICMP has no ports; expose TYPE/CODE so the row still reads cleanly.
    if ev["proto"] in ("ICMP", "ICMPV6"):
        if kv.get("TYPE", "").isdigit():
            ev["icmp_type"] = int(kv["TYPE"])
        if kv.get("CODE", "").isdigit():
            ev["icmp_code"] = int(kv["CODE"])
    for opt in ("rule", "zone_src", "zone_dst"):
        if info.get(opt):
            ev[opt] = info[opt]
    return ev


def _fetch(hours: int, fetch: int) -> list[str]:
    """Tail the most recent matching kernel-log lines from journald."""
    hours = max(1, min(int(hours), 168))
    fetch = max(50, min(int(fetch), 20000))
    args = [
        "journalctl", "-k", "--no-pager", "-o", "short-iso",
        "-g", _GREP, "--since", f"-{hours}h", "-n", str(fetch),
    ]
    res = shell.run(args, timeout=25)
    if not res.ok and not res.stdout:
        return []
    return res.stdout.splitlines()


def _matches(ev: dict[str, Any], *, src: str | None, dst: str | None,
             port: int | None, proto: str | None, action: str | None,
             category: str | None, search: str | None,
             hide_broadcast: bool) -> bool:
    if hide_broadcast and ev.get("dst") in ("255.255.255.255",) and ev.get("dpt") == 10001:
        return False
    if src and src not in (ev.get("src") or ""):
        return False
    if dst and dst not in (ev.get("dst") or ""):
        return False
    if port is not None and ev.get("spt") != port and ev.get("dpt") != port:
        return False
    if proto and (ev.get("proto") or "").upper() != proto.upper():
        return False
    if action and ev.get("action") != action:
        return False
    if category and ev.get("category") != category:
        return False
    if search:
        s = search.lower()
        hay = " ".join(str(ev.get(k) or "") for k in
                       ("src", "dst", "reason", "in_iface", "out_iface", "rule"))
        if s not in hay.lower():
            return False
    return True


def query(*, hours: int = 24, limit: int = 500, src: str | None = None,
          dst: str | None = None, port: int | None = None,
          proto: str | None = None, action: str | None = None,
          category: str | None = None, search: str | None = None,
          hide_broadcast: bool = False, fetch: int = 8000) -> dict[str, Any]:
    """Return the most recent firewall events matching the filters (newest first)."""
    lines = _fetch(hours, fetch)
    out: list[dict[str, Any]] = []
    for line in lines:
        ev = parse_line(line)
        if ev and _matches(ev, src=src, dst=dst, port=port, proto=proto,
                            action=action, category=category, search=search,
                            hide_broadcast=hide_broadcast):
            out.append(ev)
    limit = max(1, min(int(limit), 5000))
    # journald's tail ordering varies by version; sort deterministically
    # (ISO-8601 UTC strings sort chronologically) and show newest first.
    out.sort(key=lambda e: e.get("ts") or "", reverse=True)
    events = out[:limit]
    return {
        "events": events,
        "count": len(events),
        "scanned": len(lines),
        "truncated": len(out) > limit,
        "window_hours": max(1, min(int(hours), 168)),
    }


def summary(*, hours: int = 24, hide_broadcast: bool = True,
            top: int = 10, fetch: int = 12000) -> dict[str, Any]:
    """Aggregate firewall events over the window for the visibility dashboards."""
    lines = _fetch(hours, fetch)
    total = 0
    by_action: Counter[str] = Counter()
    by_category: Counter[str] = Counter()
    by_proto: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    dports: Counter[tuple[int, str]] = Counter()
    interfaces: Counter[str] = Counter()
    uniq_src: set[str] = set()
    for line in lines:
        ev = parse_line(line)
        if not ev:
            continue
        if not _matches(ev, src=None, dst=None, port=None, proto=None,
                        action=None, category=None, search=None,
                        hide_broadcast=hide_broadcast):
            continue
        total += 1
        by_action[ev["action"]] += 1
        by_category[ev["category"]] += 1
        if ev.get("proto"):
            by_proto[ev["proto"]] += 1
        if ev.get("src"):
            sources[ev["src"]] += 1
            uniq_src.add(ev["src"])
        if ev.get("dpt"):
            dports[(ev["dpt"], ev.get("proto") or "?")] += 1
        if ev.get("in_iface"):
            interfaces[ev["in_iface"]] += 1

    top = max(1, min(int(top), 50))
    return {
        "total": total,
        "scanned": len(lines),
        "unique_sources": len(uniq_src),
        "window_hours": max(1, min(int(hours), 168)),
        "by_action": dict(by_action),
        "by_category": dict(by_category),
        "by_proto": dict(by_proto.most_common(top)),
        "top_sources": [{"ip": ip, "count": c} for ip, c in sources.most_common(top)],
        "top_ports": [{"port": p, "proto": pr, "count": c}
                      for (p, pr), c in dports.most_common(top)],
        "top_interfaces": [{"iface": i, "count": c} for i, c in interfaces.most_common(top)],
    }
