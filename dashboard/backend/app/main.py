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
from .security import require_auth
from .routers import (
    ai,
    alerts,
    backup,
    content,
    firewall,
    flows,
    logs,
    network,
    overview,
    system,
    threatintel,
    waf,
)
from .services.ai import memory as ai_memory

app = FastAPI(
    title="Mundix Security 360 — Dashboard API",
    version="1.0.0",
    description="Unified security management & visibility API.",
)


@app.on_event("startup")
def _startup() -> None:
    ai_memory.init_db()
    from .services import contentcat
    contentcat.start_scheduler()
    from .services import threatintel as _ti
    _ti.start_scheduler()
    from .services import backup as _bk
    _bk.start_scheduler()


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
for r in (overview, alerts, firewall, network, content, flows, logs, system, ai, threatintel, waf, backup):
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
