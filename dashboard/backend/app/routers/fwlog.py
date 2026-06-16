"""Firewall log visibility API.

Surfaces structured nftables drop/filter events (source/destination IP, ports,
interface, reason) parsed from the kernel log, plus aggregations for the
visibility dashboards. See ``services/fwlog.py`` for the data source.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..services import fwlog

router = APIRouter(prefix="/api/fwlog", tags=["fwlog"])


@router.get("/events")
def events(
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(500, ge=1, le=5000),
    src: str | None = Query(None),
    dst: str | None = Query(None),
    port: int | None = Query(None, ge=0, le=65535),
    proto: str | None = Query(None),
    action: str | None = Query(None),
    category: str | None = Query(None),
    search: str | None = Query(None),
    hide_broadcast: bool = Query(False),
):
    try:
        return fwlog.query(
            hours=hours, limit=limit, src=src, dst=dst, port=port,
            proto=proto, action=action, category=category, search=search,
            hide_broadcast=hide_broadcast,
        )
    except Exception as e:  # pragma: no cover - resilience over 500s
        return {"events": [], "count": 0, "scanned": 0, "truncated": False,
                "window_hours": hours, "error": str(e)}


@router.get("/summary")
def summary(
    hours: int = Query(24, ge=1, le=168),
    hide_broadcast: bool = Query(True),
    top: int = Query(10, ge=1, le=50),
):
    try:
        return fwlog.summary(hours=hours, hide_broadcast=hide_broadcast, top=top)
    except Exception as e:  # pragma: no cover - resilience over 500s
        return {"total": 0, "scanned": 0, "unique_sources": 0,
                "window_hours": hours, "by_action": {}, "by_category": {},
                "by_proto": {}, "top_sources": [], "top_ports": [],
                "top_interfaces": [], "error": str(e)}
