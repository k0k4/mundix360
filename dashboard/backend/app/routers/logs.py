"""Logs API (Loki proxy)."""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..services import loki

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("")
def query_logs(
    query: str = Query('{job="suricata"}'),
    limit: int = Query(100, ge=1, le=1000),
    hours: int = Query(1, ge=1, le=168),
):
    try:
        entries = loki.query_range(query, limit=limit, hours=hours)
        return {"count": len(entries), "entries": entries}
    except Exception as e:
        return {"count": 0, "entries": [], "error": str(e)}


@router.get("/labels")
def labels():
    return {"labels": loki.labels()}
