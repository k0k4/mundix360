"""Authentication & authorization dependencies for the dashboard API.

Two credentials are accepted, in priority order:

1. A valid session cookie (``settings.session_cookie``) issued by ``/api/auth/login``
   — the primary, human-facing path. The resolved user (with its role) is stored
   on ``request.state.user`` for downstream role checks.
2. A static ``Authorization: Bearer <MUNDIX_API_TOKEN>`` — an optional machine/
   back-compat path. When used, the request acts as a synthetic ``admin`` so
   existing automation keeps working.

Until the first admin account exists (fresh appliance), every protected endpoint
returns 401 with ``X-Mundix-Setup: required`` so the SPA can route to the first-run
setup screen. Health and the ``/api/auth/*`` endpoints are never gated here.
"""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request, status

from .config import settings
from .services import users


def _bearer_ok(authorization: str | None) -> bool:
    if not settings.api_token or not authorization:
        return False
    return authorization == f"Bearer {settings.api_token}"


async def require_auth(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict:
    """Resolve and attach the current principal, or raise 401.

    Returns the public user dict and also stores it on ``request.state.user``.
    """
    # Machine token first (cheap, no DB hit).
    if _bearer_ok(authorization):
        principal = {"id": "system", "username": "system",
                     "role": "admin", "active": True, "via": "token"}
        request.state.user = principal
        return principal

    token = request.cookies.get(settings.session_cookie)
    user = users.session_user(token) if token else None
    if user:
        user["via"] = "session"
        request.state.user = user
        return user

    # Differentiate "no admin yet" (first-run) from "not logged in" so the UI can
    # send the operator to the setup screen instead of a dead login loop.
    headers = {}
    if not users.is_initialized():
        headers["X-Mundix-Setup"] = "required"
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="autenticação necessária",
        headers=headers or None,
    )


def current_user(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="autenticação necessária")
    return user


def require_role(min_role: str):
    """Dependency factory enforcing a minimum role on top of ``require_auth``."""
    floor = users.ROLE_RANK[min_role]

    async def _dep(user: dict = Depends(require_auth)) -> dict:
        if users.ROLE_RANK.get(user.get("role", "viewer"), 0) < floor:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="permissão insuficiente para esta ação",
            )
        return user

    return _dep


_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


async def protect(request: Request,
                  user: dict = Depends(require_auth)) -> dict:
    """Global guard for the data API: authenticate, then apply method-based RBAC.

    Any authenticated user may read (safe methods); changing appliance state
    (POST/PUT/PATCH/DELETE) requires at least the ``operator`` role, so a
    ``viewer`` account is effectively read-only across the whole product.
    """
    if request.method not in _SAFE_METHODS:
        if users.ROLE_RANK.get(user.get("role", "viewer"), 0) < users.ROLE_RANK["operator"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="seu perfil tem acesso somente leitura",
            )
    return user
