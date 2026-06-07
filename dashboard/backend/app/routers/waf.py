"""WAF (ModSecurity + OWASP CRS) visibility API."""
from __future__ import annotations

from fastapi import APIRouter

from ..services import waf

router = APIRouter(prefix="/api/waf", tags=["waf"])


@router.get("/summary")
def summary(limit: int = 50):
    return waf.summary(min(max(limit, 1), 200))
