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


class OpenVpnServerModel(BaseModel):
    enabled: bool = False
    proto: Literal["udp", "tcp"] = "udp"
    port: int = Field(1194, ge=1, le=65535)
    subnet: str = "10.21.0.0/24"
    dev: str = "tun0"
    dns: str = ""
    full_tunnel: bool = True
    endpoint_host: str = ""


class OpenVpnClientModel(BaseModel):
    id: Optional[str] = None
    name: str
    type: Literal["roadwarrior", "site"] = "roadwarrior"
    enabled: bool = True
    site_subnets: list[str] = Field(default_factory=list)
    local_networks: list[str] = Field(default_factory=list)
    description: str = ""


@router.put("/openvpn")
def set_openvpn(cfg: OpenVpnServerModel) -> dict[str, Any]:
    return _guard(vpn.set_openvpn, cfg.model_dump())


@router.post("/openvpn/clients")
def save_client(client: OpenVpnClientModel) -> dict[str, Any]:
    return _guard(vpn.save_client, client.model_dump(exclude_none=True))


@router.delete("/openvpn/clients/{client_id}")
def delete_client(client_id: str) -> dict[str, Any]:
    return _guard(vpn.delete_client, client_id)


@router.get("/openvpn/clients/{client_id}/config", response_class=PlainTextResponse)
def openvpn_client_config(client_id: str) -> str:
    return _guard(vpn.openvpn_client_config, client_id)


class FortinetClientModel(BaseModel):
    enabled: bool = False
    gateway_host: str = ""
    gateway_port: int = Field(443, ge=1, le=65535)
    username: str = ""
    password: Optional[str] = None
    realm: str = ""
    trusted_cert: str = ""
    iface: str = "ppp-forti"
    remote_subnets: list[str] = Field(default_factory=list)
    set_dns: bool = False
    persistent: bool = True


class FortinetProbeModel(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = Field(None, ge=1, le=65535)


@router.put("/fortinet")
def set_fortinet(cfg: FortinetClientModel) -> dict[str, Any]:
    return _guard(vpn.set_fortinet, cfg.model_dump(exclude_none=True))


@router.post("/fortinet/probe-cert")
def fortinet_probe_cert(req: FortinetProbeModel) -> dict[str, Any]:
    return _guard(vpn.fortinet_probe_cert, req.host, req.port)
