"""Network: VLAN/zones and DHCP leases."""
from __future__ import annotations

from fastapi import APIRouter

from ..services import network, system

router = APIRouter(prefix="/api/network", tags=["network"])


@router.get("/zones")
def zones():
    return {"zones": network.list_zones()}


@router.get("/dhcp-leases")
def leases():
    data = network.dhcp_leases()
    return {"count": len(data), "leases": data}


@router.get("/interfaces")
def interfaces():
    return {"interfaces": system.interfaces()}
