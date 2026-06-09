"""VPN API: WireGuard server/concentrator (road-warrior + site-to-site).

Thin HTTP layer over ``services.vpn``. Phase 1 exposes WireGuard; OpenVPN and
the Fortinet (openfortivpn) client are added in later phases under the same
``/api/vpn`` prefix.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from ..services import vpn

router = APIRouter(prefix="/api/vpn", tags=["vpn"])


class WireGuardServerModel(BaseModel):
    enabled: bool = False
    interface: str = "wg0"
    listen_port: int = Field(51820, ge=1, le=65535)
    address: str = "10.20.0.1/24"
    dns: str = ""
    endpoint_host: str = ""
    mtu: int = Field(1420, ge=1280, le=1500)


class WireGuardPeerModel(BaseModel):
    id: Optional[str] = None
    name: str
    type: Literal["roadwarrior", "site"] = "roadwarrior"
    enabled: bool = True
    address: str = ""
    public_key: str = ""
    preshared_key: Optional[str] = None
    site_subnets: list[str] = Field(default_factory=list)
    endpoint: str = ""
    keepalive: int = Field(25, ge=0, le=600)
    full_tunnel: bool = True


def _guard(fn, *args):
    try:
        return fn(*args)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
def status() -> dict[str, Any]:
    return vpn.get_status()


@router.put("/wireguard")
def set_wireguard(cfg: WireGuardServerModel) -> dict[str, Any]:
    return _guard(vpn.set_wireguard, cfg.model_dump())


@router.post("/wireguard/peers")
def save_peer(peer: WireGuardPeerModel) -> dict[str, Any]:
    return _guard(vpn.save_peer, peer.model_dump(exclude_none=True))


@router.delete("/wireguard/peers/{peer_id}")
def delete_peer(peer_id: str) -> dict[str, Any]:
    return _guard(vpn.delete_peer, peer_id)


@router.get("/wireguard/peers/{peer_id}/config", response_class=PlainTextResponse)
def peer_config(peer_id: str) -> str:
    return _guard(vpn.peer_client_config, peer_id)


@router.get("/wireguard/peers/{peer_id}/qr")
def peer_qr(peer_id: str) -> dict[str, Any]:
    return {"qr": _guard(vpn.peer_qr, peer_id)}
