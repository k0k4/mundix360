"""Optional bearer-token auth. If MUNDIX_API_TOKEN is unset, auth is disabled
(suitable for localhost-only binding behind a reverse proxy)."""
from __future__ import annotations

from fastapi import Header, HTTPException, status

from .config import settings


async def require_auth(authorization: str | None = Header(default=None)) -> None:
    if not settings.api_token:
        return
    expected = f"Bearer {settings.api_token}"
    if authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing token",
        )
