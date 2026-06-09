"""SIEM alerts API (ClickHouse akvorado.siem_alerts)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..services import clickhouse

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

_ALLOWED_SORT = {"timestamp", "severity", "source", "category"}


class TriageUpdate(BaseModel):
    false_positive: int | None = None
    triage_notes: str | None = None
    action_taken: str | None = None


@router.get("")
def list_alerts(
    hours: int = Query(24, ge=1, le=720),
    source: str | None = None,
    min_severity: int = Query(0, ge=0, le=10),
    category: str | None = None,
    search: str | None = None,
    false_positive: int | None = Query(None, ge=0, le=1),
    sort: str = Query("timestamp"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    if sort not in _ALLOWED_SORT:
        sort = "timestamp"

    where = ["timestamp > now() - INTERVAL {hours:UInt32} HOUR", "severity >= {min_sev:UInt8}"]
    params: dict[str, Any] = {"hours": hours, "min_sev": min_severity}
    if source:
        where.append("source = {source:String}")
        params["source"] = source
    if category:
        where.append("category = {category:String}")
        params["category"] = category
    if false_positive is not None:
        where.append("false_positive = {fp:UInt8}")
        params["fp"] = false_positive
    if search:
        where.append("(rule_name ILIKE {q:String} OR description ILIKE {q:String} "
                     "OR src_ip ILIKE {q:String} OR dst_ip ILIKE {q:String})")
        params["q"] = f"%{search}%"

    where_clause = " AND ".join(where)
    params["limit"] = limit
    params["offset"] = offset

    try:
        rows = clickhouse.query(
            f"""SELECT toString(event_id) AS event_id, timestamp, source, source_type,
                       rule_name, severity, category, mitre_tactic, mitre_technique,
                       src_ip, dst_ip, src_port, dst_port, protocol, hostname, user,
                       description, action_taken, false_positive, triage_notes, tags
                FROM siem_alerts
                WHERE {where_clause}
                ORDER BY {sort} DESC
                LIMIT {{limit:UInt32}} OFFSET {{offset:UInt32}}""",
            params,
        )
        total_rows = clickhouse.query(
            f"SELECT count() AS c FROM siem_alerts WHERE {where_clause}", params
        )
    except Exception:
        return {"total": 0, "count": 0, "alerts": [], "available": False}
    total = int(total_rows[0]["c"]) if total_rows else 0
    return {"total": total, "count": len(rows), "alerts": rows}


@router.get("/stats")
def alert_stats(hours: int = Query(24, ge=1, le=720)):
    params = {"hours": hours}
    try:
        by_severity = clickhouse.query(
            "SELECT severity, count() AS count FROM siem_alerts "
            "WHERE timestamp > now() - INTERVAL {hours:UInt32} HOUR "
            "GROUP BY severity ORDER BY severity DESC", params,
        )
        by_category = clickhouse.query(
            "SELECT category, count() AS count FROM siem_alerts "
            "WHERE timestamp > now() - INTERVAL {hours:UInt32} HOUR "
            "GROUP BY category ORDER BY count DESC LIMIT 10", params,
        )
        by_source = clickhouse.query(
            "SELECT source, count() AS count FROM siem_alerts "
            "WHERE timestamp > now() - INTERVAL {hours:UInt32} HOUR "
            "GROUP BY source ORDER BY count DESC LIMIT 10", params,
        )
        timeline = clickhouse.query(
            "SELECT toStartOfHour(timestamp) AS hour, count() AS count FROM siem_alerts "
            "WHERE timestamp > now() - INTERVAL {hours:UInt32} HOUR "
            "GROUP BY hour ORDER BY hour", params,
        )
    except Exception:
        return {
            "by_severity": [], "by_category": [], "by_source": [],
            "timeline": [], "available": False,
        }
    return {
        "by_severity": by_severity,
        "by_category": by_category,
        "by_source": by_source,
        "timeline": timeline,
    }


@router.get("/top-talkers")
def top_talkers(hours: int = Query(24, ge=1, le=720), limit: int = Query(10, ge=1, le=50)):
    params = {"hours": hours, "limit": limit}
    try:
        src = clickhouse.query(
            "SELECT src_ip, count() AS count FROM siem_alerts "
            "WHERE timestamp > now() - INTERVAL {hours:UInt32} HOUR AND src_ip != '' "
            "GROUP BY src_ip ORDER BY count DESC LIMIT {limit:UInt32}", params,
        )
    except Exception:
        return {"top_src_ips": [], "available": False}
    return {"top_src_ips": src}


def _alert_select(where: str) -> str:
    return (
        "SELECT toString(event_id) AS event_id, timestamp, source, source_type, "
        "rule_id, rule_name, severity, category, mitre_tactic, mitre_technique, "
        "src_ip, dst_ip, src_port, dst_port, protocol, hostname, user, "
        "description, full_log, action_taken, false_positive, triage_notes, tags "
        f"FROM siem_alerts WHERE {where} LIMIT 1"
    )


@router.get("/{event_id}")
def get_alert(event_id: str):
    rows = clickhouse.query(
        _alert_select("siem_alerts.event_id = {eid:UUID}"), {"eid": event_id}
    )
    if not rows:
        raise HTTPException(status_code=404, detail="alert not found")
    return rows[0]


@router.patch("/{event_id}")
def update_triage(event_id: str, body: TriageUpdate):
    rows = clickhouse.query(
        "SELECT count() AS c FROM siem_alerts WHERE event_id = {eid:UUID}",
        {"eid": event_id},
    )
    if not rows or int(rows[0]["c"]) == 0:
        raise HTTPException(status_code=404, detail="alert not found")

    sets: list[str] = []
    params: dict[str, Any] = {"eid": event_id}
    if body.false_positive is not None:
        sets.append("false_positive = {fp:UInt8}")
        params["fp"] = 1 if body.false_positive else 0
    if body.action_taken is not None:
        sets.append("action_taken = {act:String}")
        params["act"] = body.action_taken
    if body.triage_notes is not None:
        notes = json.dumps(
            {
                "manual_note": body.triage_notes,
                "edited_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
        )
        sets.append("triage_notes = {notes:String}")
        params["notes"] = notes

    if not sets:
        raise HTTPException(status_code=400, detail="no fields to update")

    clickhouse.command(
        f"ALTER TABLE siem_alerts UPDATE {', '.join(sets)} WHERE event_id = {{eid:UUID}}",
        params,
    )
    return {"ok": True, "event_id": event_id}
