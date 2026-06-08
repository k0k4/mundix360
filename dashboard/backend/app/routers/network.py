"""Network: VLAN/zones (CRUD), DHCP leases and static reservations."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..services import dns, fwmanage, netiface, network, system

router = APIRouter(prefix="/api/network", tags=["network"])


class ZoneModel(BaseModel):
    zone: str
    interface: str
    listen_address: str | None = None
    domain: str | None = None
    gateway: str | None = None
    dhcp_start: str | None = None
    dhcp_end: str | None = None
    netmask: str | None = None
    lease_time: str | None = "24h"
    upstream_dns: list[str] = Field(default_factory=list)


class ReservationModel(BaseModel):
    mac: str
    ip: str
    hostname: str = ""


class RecordModel(BaseModel):
    name: str
    ip: str
    aliases: list[str] = Field(default_factory=list)


class ResolversModel(BaseModel):
    resolvers: list[str] = Field(default_factory=list)


@router.get("/zones")
def zones():
    return {"zones": network.list_zones()}


@router.get("/zones/{name}")
def get_zone(name: str):
    z = network.get_zone(name)
    if not z:
        raise HTTPException(status_code=404, detail="zone not found")
    return z


@router.post("/zones")
def create_zone(z: ZoneModel):
    try:
        return network.save_zone(z.model_dump(), create=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/zones/{name}")
def update_zone(name: str, z: ZoneModel):
    data = z.model_dump()
    data["zone"] = name
    try:
        return network.save_zone(data, create=False)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/zones/{name}")
def delete_zone(name: str):
    try:
        return network.delete_zone(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/reservations")
def reservations():
    data = network.list_reservations()
    return {"count": len(data), "reservations": data}


@router.post("/reservations")
def create_reservation(r: ReservationModel):
    try:
        return network.save_reservation(r.model_dump(), create=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/reservations/{mac}")
def update_reservation(mac: str, r: ReservationModel):
    data = r.model_dump()
    data["mac"] = mac
    try:
        return network.save_reservation(data, create=False)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/reservations/{mac}")
def delete_reservation(mac: str):
    return network.delete_reservation(mac)


@router.get("/dhcp-leases")
def leases():
    data = network.dhcp_leases()
    return {"count": len(data), "leases": data}


@router.get("/dhcp/pools")
def dhcp_pools():
    return {"pools": network.dhcp_pools()}


@router.post("/dhcp-leases/{mac}/reserve")
def reserve_lease(mac: str):
    try:
        return network.reserve_lease(mac)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/interfaces")
def interfaces():
    return {"interfaces": system.interfaces()}


# --------------------------------------- adaptive interface/VLAN management ---

class InterfaceConfigModel(BaseModel):
    description: str | None = None
    admin_enabled: bool | None = None
    ipv4_mode: str | None = None  # dhcp | static | none
    address: str | None = None    # CIDR, e.g. 192.168.10.1/24
    gateway: str | None = None
    nameservers: list[str] = Field(default_factory=list)
    mtu: int | None = None
    force: bool = False


class VlanModel(BaseModel):
    parent: str
    vlan_id: int
    name: str | None = None
    description: str = ""
    ipv4_mode: str = "none"
    address: str | None = None
    gateway: str | None = None
    nameservers: list[str] = Field(default_factory=list)
    mtu: int | None = None


@router.get("/interfaces/manage")
def interfaces_manage():
    """Rich, adaptive inventory (live kernel + netplan config + roles) used by the
    professional Interfaces management screen."""
    return netiface.list_interfaces()


@router.put("/interfaces/{name}")
def update_interface(name: str, cfg: InterfaceConfigModel, request: Request):
    try:
        protect = netiface._iface_for_ip(request.client.host if request.client else None)
        return netiface.set_interface(name, protect_iface=protect, **cfg.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/vlans")
def list_vlans():
    return {"vlans": netiface.list_vlans()}


@router.post("/vlans")
def create_vlan(v: VlanModel):
    try:
        return netiface.create_vlan(**v.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.delete("/vlans/{name}")
def delete_vlan(name: str):
    try:
        return netiface.delete_vlan(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


class WanModel(BaseModel):
    interface: str = ""


@router.get("/assignments")
def assignments():
    """Detected NICs with their role (WAN / zone / unassigned) and the
    effective WAN. Fully adaptive to the host's real hardware."""
    return fwmanage.interface_assignments()


@router.put("/wan")
def set_wan(req: WanModel):
    """Pin the WAN interface (empty = auto-detect via default route)."""
    try:
        fwmanage.set_wan(req.interface)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return fwmanage.interface_assignments()


# ----------------------------------------------------------------- DNS -------
@router.get("/dns/records")
def dns_records():
    data = dns.list_records()
    return {"count": len(data), "records": data}


@router.post("/dns/records")
def create_record(r: RecordModel):
    try:
        return dns.save_record(r.model_dump(), create=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/dns/records/{name}")
def update_record(name: str, r: RecordModel):
    data = r.model_dump()
    data["name"] = name
    try:
        return dns.save_record(data, create=False)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/dns/records/{name}")
def delete_record(name: str):
    try:
        return dns.delete_record(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/dns/resolvers")
def dns_resolvers():
    return {"resolvers": dns.list_resolvers()}


@router.put("/dns/resolvers")
def set_resolvers(body: ResolversModel):
    try:
        return dns.set_resolvers(body.resolvers)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/dns/settings")
def dns_settings():
    return dns.settings_overview()


@router.get("/dns/stats")
def dns_stats():
    return dns.query_stats()


@router.get("/dns/recent")
def dns_recent(limit: int = 80):
    return dns.recent_queries(limit=limit)
