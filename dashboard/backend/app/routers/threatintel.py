"""Threat Intelligence feeds API — proactive IP/CIDR blocking."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import threatintel

router = APIRouter(prefix="/api/threatintel", tags=["threatintel"])


class ToggleRequest(BaseModel):
    enabled: bool


class AllowlistRequest(BaseModel):
    entries: list[str]


class EgressRequest(BaseModel):
    block_egress: bool


class ScheduleRequest(BaseModel):
    enabled: bool
    interval_hours: int


class UpdateRequest(BaseModel):
    feeds: list[str] | None = None


@router.get("/overview")
def overview():
    return threatintel.overview()


@router.post("/update")
def update(req: UpdateRequest):
    try:
        return threatintel.manual_update(req.feeds)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/feeds/{fid}/toggle")
def toggle_feed(fid: str, req: ToggleRequest):
    try:
        return threatintel.set_feed_enabled(fid, req.enabled)
    except KeyError:
        raise HTTPException(status_code=404, detail="feed desconhecido")
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/allowlist")
def get_allowlist():
    return {"allowlist": threatintel.load_model().get("allowlist", [])}


@router.put("/allowlist")
def put_allowlist(req: AllowlistRequest):
    try:
        return threatintel.set_allowlist(req.entries)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/egress")
def put_egress(req: EgressRequest):
    return threatintel.set_egress(req.block_egress)


@router.get("/schedule")
def get_schedule():
    return threatintel.load_model().get("schedule", {"enabled": True, "interval_hours": 6})


@router.put("/schedule")
def put_schedule(req: ScheduleRequest):
    return threatintel.set_schedule(req.enabled, req.interval_hours)
