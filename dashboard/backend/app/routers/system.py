"""System & services API."""
from __future__ import annotations

from fastapi import APIRouter

from ..services import metrics, system

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/services")
def services():
    return {"services": system.all_services()}


@router.get("/metrics")
def host_metrics():
    return system.host_metrics()


@router.get("/timeseries")
def timeseries(query: str, start: str, end: str, step: str = "60s"):
    try:
        return metrics.range_query(query, start, end, step)
    except Exception as e:
        return {"status": "error", "error": str(e)}
