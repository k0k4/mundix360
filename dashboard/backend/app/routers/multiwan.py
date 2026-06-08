"""Multi-WAN API: gateways, failover/load-balance config and live status."""
from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services import multiwan

router = APIRouter(prefix="/api/network/multiwan", tags=["multiwan"])


class GatewayModel(BaseModel):
    id: Optional[str] = None
    name: str
    iface: str
    gateway: str = "auto"
    monitor_ip: str = "8.8.8.8"
    weight: int = Field(1, ge=1, le=256)
    tier: int = Field(1, ge=1, le=10)
    enabled: bool = True


class ConfigModel(BaseModel):
    enabled: bool = False
    mode: Literal["failover", "loadbalance"] = "failover"
    interval: int = Field(10, ge=3, le=120)
    down_after: int = Field(3, ge=1, le=10)
    up_after: int = Field(2, ge=1, le=10)
    gateways: list[GatewayModel] = Field(default_factory=list)


def _guard(fn, *args):
    try:
        return fn(*args)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
def status() -> dict[str, Any]:
    return multiwan.get_status()


@router.put("/config")
def set_config(cfg: ConfigModel) -> dict[str, Any]:
    return _guard(multiwan.set_config, cfg.model_dump())


@router.post("/apply")
def apply() -> dict[str, Any]:
    return _guard(multiwan.apply_routing)
