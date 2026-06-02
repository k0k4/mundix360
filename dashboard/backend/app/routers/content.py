"""Content filtering API (DNS sinkhole)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import content

router = APIRouter(prefix="/api/content", tags=["content"])


class DomainRequest(BaseModel):
    domain: str
    note: str = ""


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


@router.delete("/blocklist/{domain}")
def remove_domain(domain: str):
    return content.remove_domain(domain)
