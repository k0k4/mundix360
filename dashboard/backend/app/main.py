"""Mundix Security 360 — Dashboard backend (FastAPI).

Single, unified API for security management and visibility:
SIEM alerts, firewall (rules, IP blocklist, port rules), VLAN/network,
content filtering, NetFlow, logs and system/service status.
"""
from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .security import require_auth
from .routers import (
    alerts,
    content,
    firewall,
    flows,
    logs,
    network,
    overview,
    system,
)

app = FastAPI(
    title="Mundix Security 360 — Dashboard API",
    version="1.0.0",
    description="Unified security management & visibility API.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "service": "mundix360-dashboard-api"}


_protected = [Depends(require_auth)]
for r in (overview, alerts, firewall, network, content, flows, logs, system):
    app.include_router(r.router, dependencies=_protected)
