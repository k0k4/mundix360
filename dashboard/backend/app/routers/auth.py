"""Authentication & user-management endpoints.

Mounted WITHOUT the global ``protect`` dependency so login/setup/state stay
reachable for anonymous clients. Per-route guards enforce the rest:

- ``/state``  (open)  — first-run/initialised probe for the SPA.
- ``/setup``  (open, one-shot) — create the first admin on a fresh appliance.
- ``/login`` / ``/logout`` — session lifecycle (HttpOnly cookie).
- ``/me`` / ``/change-password`` — the current session's own account.
- ``/users`` CRUD — admin-only user management.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from ..config import settings
from ..security import current_user, require_auth, require_role
from ..services import users

router = APIRouter(prefix="/api/auth", tags=["auth"])


# --- models ----------------------------------------------------------------
class LoginIn(BaseModel):
    username: str
    password: str


class SetupIn(BaseModel):
    username: str
    password: str
    full_name: str = ""


class CreateUserIn(BaseModel):
    username: str
    password: str
    role: str = "operator"
    full_name: str = ""
    active: bool = True


class UpdateUserIn(BaseModel):
    role: str | None = None
    active: bool | None = None
    full_name: str | None = None
    password: str | None = Field(default=None, min_length=0)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


# --- helpers ---------------------------------------------------------------
def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie,
        value=token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=settings.session_cookie, path="/")


# --- public ----------------------------------------------------------------
@router.get("/state")
def state():
    """Whether an admin exists yet (drives the SPA login vs. first-run setup)."""
    return {
        "initialized": users.is_initialized(),
        "user_count": users.count_users(),
        "auth_required": True,
    }


@router.post("/setup", status_code=status.HTTP_201_CREATED)
def setup(body: SetupIn, request: Request, response: Response):
    """Create the first administrator. Only works while no admin exists."""
    if users.is_initialized():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="o sistema já foi inicializado",
        )
    try:
        user = users.create_user(
            body.username, body.password, role="admin",
            full_name=body.full_name, active=True)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    token = users.create_session(
        user["id"], ip=_client_ip(request),
        user_agent=request.headers.get("user-agent", ""))
    _set_session_cookie(response, token)
    return {"user": user}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    try:
        user = users.authenticate(
            body.username, body.password, ip=_client_ip(request))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    token = users.create_session(
        user["id"], ip=_client_ip(request),
        user_agent=request.headers.get("user-agent", ""))
    _set_session_cookie(response, token)
    return {"user": user}


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(settings.session_cookie)
    if token:
        users.destroy_session(token)
    _clear_session_cookie(response)
    return {"ok": True}


# --- current account -------------------------------------------------------
@router.get("/me")
def me(user: dict = Depends(require_auth)):
    return {"user": {k: v for k, v in user.items() if k != "via"},
            "via": user.get("via")}


@router.post("/change-password")
def change_password(body: ChangePasswordIn, request: Request,
                    user: dict = Depends(require_auth)):
    if user.get("via") == "token":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="a sessão por token não possui senha para alterar")
    # Re-verify the current password against the live record.
    try:
        users.authenticate(user["username"], body.current_password,
                            ip=_client_ip(request))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="senha atual incorreta")
    try:
        users.set_password(user["id"], body.new_password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    # Password change drops all sessions; issue a fresh one for this client.
    token = users.create_session(
        user["id"], ip=_client_ip(request),
        user_agent=request.headers.get("user-agent", ""))
    resp = Response(status_code=status.HTTP_200_OK)
    _set_session_cookie(resp, token)
    return resp


# --- user management (admin) -----------------------------------------------
@router.get("/users")
def list_users(_: dict = Depends(require_role("admin"))):
    return {"users": users.list_users()}


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(body: CreateUserIn, _: dict = Depends(require_role("admin"))):
    try:
        return users.create_user(
            body.username, body.password, role=body.role,
            full_name=body.full_name, active=body.active)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/users/{user_id}")
def update_user(user_id: str, body: UpdateUserIn,
                _: dict = Depends(require_role("admin"))):
    try:
        return users.update_user(
            user_id,
            role=body.role,
            active=body.active,
            full_name=body.full_name,
            password=body.password or None,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/users/{user_id}")
def delete_user(user_id: str, actor: dict = Depends(require_role("admin"))):
    if actor.get("id") == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="você não pode excluir a própria conta")
    try:
        users.delete_user(user_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"ok": True}
