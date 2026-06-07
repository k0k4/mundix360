"""WAF (ModSecurity + OWASP CRS) visibility.

Read-only insight into the nginx/ModSecurity WAF that fronts the dashboard:
engine status and a parsed view of the most recent audit-log events (blocked
requests, matched CRS rule ids, anomaly scores). Management of the rules
themselves is intentionally out of band (files under /etc/nginx/modsec) to
avoid a self-inflicted lockout from the UI.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from typing import Any

AUDIT_LOG = "/var/log/nginx/modsec_audit.log"
OVERRIDES = "/etc/nginx/modsec/mundix-overrides.conf"
TAIL_BYTES = 3_000_000  # parse only the tail to stay fast

_BOUNDARY = re.compile(r"^---([A-Za-z0-9]+)---([A-Z])--\s*$")
_ID = re.compile(r'\[id "(\d+)"\]')
_MSG = re.compile(r'\[msg "([^"]+)"\]')
_SCORE = re.compile(r"Inbound Anomaly Score Exceeded \(Total Score: (\d+)\)")


def _read_tail() -> str:
    try:
        size = os.path.getsize(AUDIT_LOG)
        with open(AUDIT_LOG, "r", errors="replace") as f:
            if size > TAIL_BYTES:
                f.seek(size - TAIL_BYTES)
                f.readline()  # discard partial line
            return f.read()
    except OSError:
        return ""


def _parse(text: str) -> list[dict[str, Any]]:
    """Group audit-log lines into transactions keyed by section letter."""
    txns: dict[str, dict[str, list[str]]] = {}
    order: list[str] = []
    cur_id = cur_part = None
    for line in text.splitlines():
        m = _BOUNDARY.match(line)
        if m:
            cur_id, cur_part = m.group(1), m.group(2)
            if cur_id not in txns:
                txns[cur_id] = {}
                order.append(cur_id)
            txns[cur_id].setdefault(cur_part, [])
            continue
        if cur_id is not None and cur_part is not None:
            txns[cur_id][cur_part].append(line)

    events: list[dict[str, Any]] = []
    for tid in order:
        parts = txns[tid]
        a = (parts.get("A") or [""])[0]
        b = (parts.get("B") or [""])[0]
        f_status = ""
        if parts.get("F"):
            sl = parts["F"][0].split()
            f_status = sl[1] if len(sl) > 1 else ""
        h = "\n".join(parts.get("H", []))

        ts = client = ""
        am = re.match(r"\[([^\]]+)\]\s+\S+\s+(\S+)\s+\d+\s+(\S+)", a)
        if am:
            ts, client = am.group(1), am.group(2)
        method = uri = ""
        bm = re.match(r"(\S+)\s+(\S+)", b)
        if bm:
            method, uri = bm.group(1), bm.group(2)

        ids = _ID.findall(h)
        msgs = _MSG.findall(h)
        score_m = _SCORE.search(h)
        score = int(score_m.group(1)) if score_m else None
        blocked = f_status == "403" or any(i == "949110" for i in ids)

        if not ids and not blocked:
            continue  # only surface transactions that matched something
        events.append({
            "id": tid, "time": ts, "client": client, "method": method,
            "uri": uri[:200], "status": f_status, "blocked": blocked,
            "score": score, "rule_ids": ids,
            "messages": [m for m in msgs if "Anomaly Score" not in m][:6],
        })
    return events


def _engine_on() -> bool:
    try:
        with open(OVERRIDES) as f:
            return re.search(r"^\s*SecRuleEngine\s+On\b", f.read(), re.M) is not None
    except OSError:
        return False


def summary(limit: int = 50) -> dict[str, Any]:
    events = _parse(_read_tail())
    blocked = [e for e in events if e["blocked"]]
    rule_counter: Counter[str] = Counter()
    for e in blocked:
        for rid in e["rule_ids"]:
            if rid not in ("949110", "980130"):  # scoring/summary meta-rules
                rule_counter[rid] += 1
    # attach the most relevant message per top rule for readability
    msg_by_id: dict[str, str] = {}
    for e in blocked:
        for rid, msg in zip(e["rule_ids"], e["messages"] + [""] * len(e["rule_ids"])):
            msg_by_id.setdefault(rid, msg)
    top_rules = [{"id": rid, "count": c, "msg": msg_by_id.get(rid, "")}
                 for rid, c in rule_counter.most_common(8)]
    recent = list(reversed(events))[:limit]
    return {
        "engine_on": _engine_on(),
        "log_present": os.path.exists(AUDIT_LOG),
        "total_matched": len(events),
        "total_blocked": len(blocked),
        "top_rules": top_rules,
        "recent": recent,
    }
