"""Firewall management API: ruleset, IP blocklist, port rules, managed rules/NAT."""
from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..services import firewall, fwmanage

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


# =================================================================== managed ===
# Managed firewall: pfSense/OPNsense-style rules + NAT (see services/fwmanage).


class FilterRuleModel(BaseModel):
    id: Optional[str] = None
    chain: Literal["input", "forward"]
    enabled: bool = True
    action: Literal["accept", "drop", "reject"] = "accept"
    iif: Optional[str] = None
    oif: Optional[str] = None
    proto: Literal["tcp", "udp", "icmp", "any"] = "any"
    source: str = "any"
    dest: str = "any"
    dport: str = ""
    log: bool = False
    log_rate: Optional[str] = None
    rate_limit: Optional[str] = None
    conn_limit: Optional[int] = Field(None, ge=0, le=1000000)
    description: str = ""
    order: Optional[int] = None


class PortForwardModel(BaseModel):
    id: Optional[str] = None
    enabled: bool = True
    iif: str = ""  # empty = WAN (resolved live by fwmanage)
    proto: Literal["tcp", "udp"] = "tcp"
    dport: str
    to_ip: str
    to_port: Optional[str] = None
    source: str = "any"
    description: str = ""


class AliasModel(BaseModel):
    id: Optional[str] = None
    name: str
    type: Literal["host", "network", "port", "group"]
    values: list[str]
    description: str = ""


class OutboundModel(BaseModel):
    mode: Literal["auto", "manual"] = "auto"
    rules: list[dict[str, Any]] = Field(default_factory=list)


class ForwardingModel(BaseModel):
    enabled: bool


def _guard(fn, *args, revert_after: int = 0):
    try:
        if revert_after and revert_after > 0:
            with fwmanage.arm_revert(min(int(revert_after), 600)):
                return fn(*args)
        return fn(*args)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/overview")
def fw_overview():
    return fwmanage.overview()


class ZonePolicyModel(BaseModel):
    action: Literal["allow", "block"]
    log: bool = True


@router.get("/zone-policies")
def get_zone_policies():
    return fwmanage.list_zone_policies()


@router.put("/zone-policies/{src}/{dst}")
def put_zone_policy(src: str, dst: str, body: ZonePolicyModel,
                    revert_after: int = Query(0, ge=0, le=600)):
    _guard(fwmanage.set_zone_policy, src, dst, body.action, body.log,
           revert_after=revert_after)
    return fwmanage.pending_status()


@router.get("/rules")
def get_rules():
    rules = fwmanage.list_rules()
    return {"count": len(rules), "rules": rules}


@router.post("/rules")
def create_rule(r: FilterRuleModel, revert_after: int = Query(0, ge=0, le=600)):
    _guard(fwmanage.save_rule, r.model_dump(exclude_none=True),
           revert_after=revert_after)
    return fwmanage.pending_status()


@router.put("/rules/{rid}")
def update_rule(rid: str, r: FilterRuleModel,
                revert_after: int = Query(0, ge=0, le=600)):
    data = r.model_dump(exclude_none=True)
    data["id"] = rid
    _guard(fwmanage.save_rule, data, revert_after=revert_after)
    return fwmanage.pending_status()


@router.delete("/rules/{rid}")
def remove_rule(rid: str, revert_after: int = Query(0, ge=0, le=600)):
    _guard(fwmanage.delete_rule, rid, revert_after=revert_after)
    return fwmanage.pending_status()


@router.post("/rules/{rid}/move/{direction}")
def reorder_rule(rid: str, direction: Literal["up", "down"]):
    _guard(fwmanage.move_rule, rid, direction)
    return {"ok": True}


@router.get("/port-forwards")
def get_port_forwards():
    pfs = fwmanage.list_port_forwards()
    return {"count": len(pfs), "port_forwards": pfs}


@router.post("/port-forwards")
def create_port_forward(p: PortForwardModel):
    _guard(fwmanage.save_port_forward, p.model_dump(exclude_none=True))
    return {"ok": True}


@router.put("/port-forwards/{pid}")
def update_port_forward(pid: str, p: PortForwardModel):
    data = p.model_dump(exclude_none=True)
    data["id"] = pid
    _guard(fwmanage.save_port_forward, data)
    return {"ok": True}


@router.delete("/port-forwards/{pid}")
def remove_port_forward(pid: str):
    _guard(fwmanage.delete_port_forward, pid)
    return {"ok": True}


@router.get("/aliases")
def get_aliases():
    aliases = fwmanage.list_aliases()
    return {"count": len(aliases), "aliases": aliases}


@router.post("/aliases")
def create_alias(a: AliasModel):
    _guard(fwmanage.save_alias, a.model_dump(exclude_none=True))
    return {"ok": True}


@router.put("/aliases/{aid}")
def update_alias(aid: str, a: AliasModel):
    data = a.model_dump(exclude_none=True)
    data["id"] = aid
    _guard(fwmanage.save_alias, data)
    return {"ok": True}


@router.delete("/aliases/{aid}")
def remove_alias(aid: str):
    _guard(fwmanage.delete_alias, aid)
    return {"ok": True}


@router.get("/outbound")
def get_outbound():
    return fwmanage.get_outbound()


@router.put("/outbound")
def put_outbound(o: OutboundModel):
    _guard(fwmanage.set_outbound, o.model_dump())
    return {"ok": True}


@router.get("/forwarding")
def get_forwarding():
    return fwmanage.get_forwarding()


@router.put("/forwarding")
def put_forwarding(f: ForwardingModel):
    return _guard(fwmanage.set_forwarding, f.enabled)


@router.get("/hardening")
def get_hardening():
    return fwmanage.get_hardening()


@router.post("/hardening/apply")
def post_hardening():
    return _guard(fwmanage.apply_hardening)


class ConfirmModel(BaseModel):
    token: str


@router.get("/pending")
def get_pending():
    return fwmanage.pending_status()


@router.post("/confirm")
def post_confirm(body: ConfirmModel):
    return _guard(fwmanage.confirm_pending, body.token)
