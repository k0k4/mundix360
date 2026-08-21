"""System & services API."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import metrics, system, updates

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


# --- Canal de atualizações estáveis (repo APT assinado, só o pacote mundix360)

@router.get("/updates")
def updates_overview():
    return updates.overview()


@router.post("/updates/check")
def updates_check():
    result = updates.check(force=True)
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return result


@router.post("/updates/apply")
def updates_apply():
    try:
        return updates.apply_async()
    except updates.UpdateInProgress:
        raise HTTPException(status_code=409,
                            detail="já há uma atualização em andamento")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/updates/status")
def updates_status():
    return updates.status()
