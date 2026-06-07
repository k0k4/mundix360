"""Content filtering API (DNS sinkhole)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import content, contentcat, dnslog

router = APIRouter(prefix="/api/content", tags=["content"])


class DomainRequest(BaseModel):
    domain: str
    note: str = ""


class ToggleRequest(BaseModel):
    enabled: bool


class AllowlistRequest(BaseModel):
    domains: list[str]


class CustomSourceRequest(BaseModel):
    id: str
    category: str
    name: str = ""
    url: str
    format: str = "hosts"
    description: str = ""


class ScheduleRequest(BaseModel):
    enabled: bool
    interval_hours: int


@router.get("/blocklist")
def list_domains():
    domains = content.list_blocked_domains()
    return {"count": len(domains), "domains": domains}


@router.post("/blocklist")
def add_domain(req: DomainRequest):
    try:
        return content.add_domain(req.domain, req.note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/blocklist/{domain}")
def update_domain(domain: str, req: DomainRequest):
    try:
        # add_domain is idempotent (overwrites note for existing domain)
        return content.add_domain(domain, req.note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/blocklist/{domain}")
def remove_domain(domain: str):
    return content.remove_domain(domain)


# --------------------------------------------------------- categories / lists


@router.get("/overview")
def categories_overview():
    return contentcat.overview()


@router.get("/catalog")
def catalog():
    return {"sources": contentcat.list_catalog(), "categories": contentcat.CATEGORIES}


@router.post("/categories/{cid}/toggle")
def toggle_category(cid: str, req: ToggleRequest):
    try:
        return contentcat.set_category_enabled(cid, req.enabled)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/categories/{cid}/update")
def update_category(cid: str):
    if cid not in contentcat.CATEGORIES:
        raise HTTPException(status_code=404, detail="categoria desconhecida")
    try:
        return contentcat.manual_update([cid])
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/categories/update-all")
def update_all_categories():
    try:
        return contentcat.manual_update(None)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


# ------------------------------------------------------------------ allowlist


@router.get("/allowlist")
def get_allowlist():
    return {"domains": contentcat.get_allowlist()}


@router.put("/allowlist")
def put_allowlist(req: AllowlistRequest):
    try:
        return contentcat.set_allowlist(req.domains)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


# -------------------------------------------------------------- custom sources


@router.post("/sources")
def add_source(req: CustomSourceRequest):
    try:
        return contentcat.add_custom_source(req.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/sources/{sid}")
def delete_source(sid: str):
    return contentcat.delete_custom_source(sid)


@router.post("/sources/{sid}/toggle")
def toggle_source(sid: str, req: ToggleRequest):
    return contentcat.toggle_source(sid, req.enabled)


# ------------------------------------------------------------------- schedule


@router.get("/schedule")
def get_schedule():
    return contentcat.get_schedule()


@router.put("/schedule")
def put_schedule(req: ScheduleRequest):
    return contentcat.set_schedule(req.enabled, req.interval_hours)


# ------------------------------------------------- real-time DNS visibility


@router.get("/queries")
def dns_queries(
    search: str = "",
    client: str = "",
    status: str = "",
    qtype: str = "",
    limit: int = 200,
    offset: int = 0,
):
    if not dnslog.available():
        return {"available": False, "total": 0, "events": [],
                "limit": limit, "offset": offset}
    limit = max(1, min(limit, 1000))
    offset = max(0, offset)
    return dnslog.query_feed(
        search=search, client=client, status=status, qtype=qtype,
        limit=limit, offset=offset,
    )


@router.get("/queries/stats")
def dns_query_stats(top: int = 10):
    top = max(1, min(top, 50))
    return dnslog.stats(top=top)

