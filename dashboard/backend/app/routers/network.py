"""Network: VLAN/zones (CRUD), DHCP leases and static reservations."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services import network, system

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


@router.get("/interfaces")
def interfaces():
    return {"interfaces": system.interfaces()}
