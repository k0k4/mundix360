"""Mundix Security 360 — Dashboard backend (FastAPI).

Single, unified API for security management and visibility:
SIEM alerts, firewall (rules, IP blocklist, port rules), VLAN/network,
content filtering, NetFlow, logs and system/service status.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .security import protect
from .routers import (
    ai,
    alerts,
    auth,
    backup,
    content,
    firewall,
    flows,
    logs,
    multiwan,
    network,
    overview,
    system,
    threatintel,
    vpn,
    waf,
)
from .services.ai import memory as ai_memory
from .services import users as auth_users

app = FastAPI(
    title="Mundix Security 360 — Dashboard API",
    version="1.0.0",
    description="Unified security management & visibility API.",
)


@app.on_event("startup")
def _startup() -> None:
    ai_memory.init_db()
    auth_users.init_db()
    auth_users.purge_expired()
    from .services import contentcat
    contentcat.start_scheduler()
    from .services import threatintel as _ti
    _ti.start_scheduler()
    from .services import backup as _bk
    _bk.start_scheduler()
    # Foundation hardening: ensure the kernel anti-spoof/redirect posture is in
    # place on every boot, regardless of which appliance this image runs on.
    try:
        from .services import fwmanage as _fw
        _fw.apply_hardening()
        # Self-heal the firewall base: re-apply the intended ruleset if the live
        # kernel state is missing or has drifted from the model (e.g. after a
        # reboot race or a code update that changed render()).
        _fw.reconcile()
        # Multi-WAN monitor (no-op unless the operator enabled it).
        from .services import multiwan as _mw
        _mw.start_monitor()
    except Exception:
        pass


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


# Authentication endpoints are intentionally NOT behind `protect` (login/setup
# must be reachable anonymously); they enforce their own per-route guards.
app.include_router(auth.router)

_protected = [Depends(protect)]
for r in (overview, alerts, firewall, network, content, flows, logs, system, ai, threatintel, waf, backup, multiwan, vpn):
    app.include_router(r.router, dependencies=_protected)


# --- Serve the Refine SPA (production build) -------------------------------
_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

if _FRONTEND_DIST.is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=_FRONTEND_DIST / "assets"),
        name="assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        candidate = _FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_FRONTEND_DIST / "index.html")
