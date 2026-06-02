"""Firewall management API: ruleset, IP blocklist, port rules."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services import firewall

router = APIRouter(prefix="/api/firewall", tags=["firewall"])


class BlockRequest(BaseModel):
    ip: str
    duration: int = Field(3600, ge=60, le=2592000)
    reason: str = "dashboard"


class PortRuleRequest(BaseModel):
    proto: str = Field(pattern="^(tcp|udp)$")
    port: int = Field(ge=1, le=65535)
    action: str = Field("accept", pattern="^(accept|drop)$")
    iif: str | None = None


@router.get("/ruleset")
def get_ruleset():
    return firewall.list_ruleset()


@router.get("/blocklist")
def get_blocklist():
    blocked = firewall.list_blocked()
    return {"count": len(blocked), "blocked": blocked}


@router.post("/blocklist")
def add_block(req: BlockRequest):
    try:
        result = firewall.block_ip(req.ip, req.duration, req.reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not result["ok"]:
        raise HTTPException(status_code=500, detail=result.get("stderr") or "block failed")
    return result


@router.delete("/blocklist/{ip}")
def remove_block(ip: str):
    try:
        result = firewall.unblock_ip(ip)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not result["ok"]:
        raise HTTPException(status_code=500, detail=result.get("stderr") or "unblock failed")
    return result


@router.get("/input-rules")
def get_input_rules():
    rules = firewall.list_input_rules()
    return {"count": len(rules), "rules": rules}


@router.post("/port-rules")
def add_port_rule(req: PortRuleRequest):
    try:
        result = firewall.add_port_rule(req.proto, req.port, req.action, req.iif)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not result["ok"]:
        raise HTTPException(status_code=500, detail=result.get("stderr") or "rule add failed")
    return result


@router.delete("/input-rules/{handle}")
def delete_input_rule(handle: int):
    result = firewall.delete_input_rule(handle)
    if not result["ok"]:
        raise HTTPException(status_code=500, detail=result.get("stderr") or "delete failed")
    return result
