"""System & services API."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import metrics, system

router = APIRouter(prefix="/api/system", tags=["system"])


class ServiceAction(BaseModel):
    action: str


@router.get("/services")
def services():
    return {"services": system.all_services()}


@router.post("/services/{name}/action")
def control(name: str, body: ServiceAction):
    try:
        result = system.control_service(name, body.action)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not result["ok"]:
        raise HTTPException(status_code=500, detail=result.get("stderr") or "action failed")
    return result


@router.get("/metrics")
def host_metrics():
    return system.host_metrics()


@router.get("/timeseries")
def timeseries(query: str, start: str, end: str, step: str = "60s"):
    try:
        return metrics.range_query(query, start, end, step)
    except Exception as e:
        return {"status": "error", "error": str(e)}
