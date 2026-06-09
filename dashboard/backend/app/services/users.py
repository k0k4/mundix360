"""Local user accounts, authentication and opaque sessions for the dashboard.

SQLite-backed (WAL), appliance-local, root-only file (same trust model as the AI
DB). Security properties:

- Passwords are stored only as PBKDF2-SHA256 hashes (stdlib, no external deps),
  matching the convention already used for the AI master password.
- Sessions are opaque random tokens; only the SHA-256 of the token is persisted,
  so a DB leak never yields a usable session. Tokens carry an absolute expiry.
- Constant-time comparisons everywhere a secret is checked.
- Role model: ``admin`` (full, incl. user management), ``operator`` (read+write
  appliance config) and ``viewer`` (read-only). The system refuses to delete or
  demote the last remaining admin to avoid an irrecoverable lockout.

Recovery: ``app.admin`` (local root CLI) can always create/reset an admin, mirror-
ing the master-password recovery anchor.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ..config import settings

ROLES = ("admin", "operator", "viewer")
# Mutating the appliance requires at least operator; user management requires admin.
ROLE_RANK = {"viewer": 0, "operator": 1, "admin": 2}

_USERNAME_MAX = 64
_PASSWORD_MIN = 8
_PASSWORD_MAX = 256
_PBKDF2_ITERS = 200_000

# Brute-force throttle: lock a username/IP pair after too many failures within a
# rolling window. In-memory (per-process) — adequate for a single-node appliance.
_MAX_FAILS = 8
_LOCK_WINDOW = 300  # seconds
_fails: dict[str, list[float]] = {}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'operator',
    full_name     TEXT,
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    REAL,
    updated_at    REAL,
    last_login    REAL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    created_at  REAL,
    expires_at  REAL,
    last_seen   REAL,
    ip          TEXT,
    user_agent  TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_exp  ON sessions(expires_at);
"""

_lock = threading.RLock()
_initialized = False


def _db_path() -> str:
    return getattr(settings, "auth_db_path", "") or \
        "/opt/mundix360/dashboard/backend/data/auth.db"


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    path = _db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        yield con
        con.commit()
    finally:
        con.close()


def init_db() -> None:
    global _initialized
    with _lock:
        with _conn() as con:
            con.executescript(_SCHEMA)
        # Tighten file perms — the DB holds password hashes and live sessions.
        try:
            os.chmod(_db_path(), 0o600)
        except OSError:
            pass
        _initialized = True


# --- password hashing ------------------------------------------------------
def hash_password(plain: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt, _PBKDF2_ITERS)
    return f"pbkdf2_sha256${_PBKDF2_ITERS}${salt.hex()}${dk.hex()}"


def verify_password(plain: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", plain.encode(), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# --- validation ------------------------------------------------------------
def validate_username(name: str) -> str:
    name = (name or "").strip()
    if not name or len(name) > _USERNAME_MAX:
        raise ValueError("nome de usuário inválido (1–64 caracteres)")
    if not all(c.isalnum() or c in "._-@" for c in name):
        raise ValueError("nome de usuário: use apenas letras, números e . _ - @")
    return name


def validate_password(pw: str) -> str:
    if pw is None or len(pw) < _PASSWORD_MIN:
        raise ValueError(f"a senha deve ter ao menos {_PASSWORD_MIN} caracteres")
    if len(pw) > _PASSWORD_MAX:
        raise ValueError("senha muito longa")
    return pw


def validate_role(role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"perfil inválido (use: {', '.join(ROLES)})")
    return role


# --- serialization ---------------------------------------------------------
def _public(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "full_name": row["full_name"] or "",
        "active": bool(row["active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_login": row["last_login"],
    }


# --- queries ---------------------------------------------------------------
def count_users() -> int:
    with _conn() as con:
        return int(con.execute("SELECT COUNT(*) c FROM users").fetchone()["c"])


def is_initialized() -> bool:
    """True once at least one (active) admin exists."""
    with _conn() as con:
        row = con.execute(
            "SELECT COUNT(*) c FROM users WHERE role='admin' AND active=1"
        ).fetchone()
    return int(row["c"]) > 0


def _count_active_admins(con: sqlite3.Connection, exclude_id: str | None = None) -> int:
    q = "SELECT COUNT(*) c FROM users WHERE role='admin' AND active=1"
    args: tuple = ()
    if exclude_id:
        q += " AND id<>?"
        args = (exclude_id,)
    return int(con.execute(q, args).fetchone()["c"])


def list_users() -> list[dict[str, Any]]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM users ORDER BY username").fetchall()
    return [_public(r) for r in rows]


def get_user(user_id: str) -> dict[str, Any] | None:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return _public(row) if row else None


def _get_by_name(con: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    return con.execute(
        "SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)
    ).fetchone()


# --- mutations -------------------------------------------------------------
def create_user(username: str, password: str, role: str = "operator",
                full_name: str = "", active: bool = True) -> dict[str, Any]:
    username = validate_username(username)
    validate_password(password)
    role = validate_role(role)
    now = time.time()
    uid = uuid.uuid4().hex
    with _lock, _conn() as con:
        if _get_by_name(con, username):
            raise ValueError("já existe um usuário com esse nome")
        con.execute(
            "INSERT INTO users (id, username, password_hash, role, full_name, "
            "active, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (uid, username, hash_password(password), role, full_name.strip(),
             1 if active else 0, now, now),
        )
        row = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return _public(row)


def update_user(user_id: str, *, role: str | None = None,
                active: bool | None = None, full_name: str | None = None,
                password: str | None = None) -> dict[str, Any]:
    with _lock, _conn() as con:
        row = con.execute(
            "SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            raise ValueError("usuário não encontrado")

        new_role = row["role"] if role is None else validate_role(role)
        new_active = row["active"] if active is None else (1 if active else 0)

        # Anti-lockout: never leave the system without an active admin.
        was_admin = row["role"] == "admin" and row["active"] == 1
        will_be_admin = new_role == "admin" and new_active == 1
        if was_admin and not will_be_admin and _count_active_admins(con, exclude_id=user_id) == 0:
            raise ValueError(
                "não é possível rebaixar/desativar o último administrador ativo")

        sets = ["role=?", "active=?", "updated_at=?"]
        args: list[Any] = [new_role, new_active, time.time()]
        if full_name is not None:
            sets.append("full_name=?")
            args.append(full_name.strip())
        if password is not None:
            validate_password(password)
            sets.append("password_hash=?")
            args.append(hash_password(password))
        args.append(user_id)
        con.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", args)
        # A password/role/active change invalidates the user's other sessions.
        if password is not None or new_active == 0:
            con.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        out = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return _public(out)


def delete_user(user_id: str) -> None:
    with _lock, _conn() as con:
        row = con.execute(
            "SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            raise ValueError("usuário não encontrado")
        if row["role"] == "admin" and row["active"] == 1 \
                and _count_active_admins(con, exclude_id=user_id) == 0:
            raise ValueError("não é possível excluir o último administrador ativo")
        con.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        con.execute("DELETE FROM users WHERE id=?", (user_id,))


def set_password(user_id: str, new_password: str) -> None:
    update_user(user_id, password=new_password)


# --- authentication --------------------------------------------------------
def _throttle_key(username: str, ip: str) -> str:
    return f"{(username or '').lower()}|{ip or ''}"


def _is_locked(key: str) -> bool:
    now = time.time()
    hits = [t for t in _fails.get(key, []) if now - t < _LOCK_WINDOW]
    _fails[key] = hits
    return len(hits) >= _MAX_FAILS


def _record_fail(key: str) -> None:
    _fails.setdefault(key, []).append(time.time())


def _clear_fail(key: str) -> None:
    _fails.pop(key, None)


def authenticate(username: str, password: str, ip: str = "") -> dict[str, Any]:
    """Return the public user dict on success. Raises ValueError otherwise.

    Performs a dummy hash on unknown users to keep timing uniform, and applies a
    per-(username, ip) lockout to blunt brute-force."""
    key = _throttle_key(username, ip)
    if _is_locked(key):
        raise ValueError("muitas tentativas; tente novamente em alguns minutos")
    with _conn() as con:
        row = _get_by_name(con, (username or "").strip())
        stored = row["password_hash"] if row else \
            "pbkdf2_sha256$1$00$00"  # dummy, constant-time-ish
        ok = verify_password(password or "", stored)
        if not row or not ok or row["active"] != 1:
            _record_fail(key)
            raise ValueError("usuário ou senha inválidos")
        con.execute("UPDATE users SET last_login=? WHERE id=?",
                    (time.time(), row["id"]))
        out = _public(row)
    _clear_fail(key)
    return out


# --- sessions --------------------------------------------------------------
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _ttl_seconds() -> int:
    return int(getattr(settings, "session_ttl_hours", 12)) * 3600


def create_session(user_id: str, ip: str = "", user_agent: str = "") -> str:
    """Create a session and return the RAW token (shown once, set as cookie)."""
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _conn() as con:
        con.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at, "
            "last_seen, ip, user_agent) VALUES (?,?,?,?,?,?,?)",
            (_hash_token(token), user_id, now, now + _ttl_seconds(), now,
             ip, (user_agent or "")[:256]),
        )
    return token


def session_user(token: str) -> dict[str, Any] | None:
    """Validate a raw session token; return the public user or None.

    Sliding refresh: extends the expiry on activity so an active operator is not
    logged out mid-session, while idle sessions still expire."""
    if not token:
        return None
    th = _hash_token(token)
    now = time.time()
    with _conn() as con:
        s = con.execute(
            "SELECT * FROM sessions WHERE token_hash=?", (th,)).fetchone()
        if not s:
            return None
        if s["expires_at"] is not None and s["expires_at"] < now:
            con.execute("DELETE FROM sessions WHERE token_hash=?", (th,))
            return None
        u = con.execute(
            "SELECT * FROM users WHERE id=?", (s["user_id"],)).fetchone()
        if not u or u["active"] != 1:
            con.execute("DELETE FROM sessions WHERE token_hash=?", (th,))
            return None
        con.execute(
            "UPDATE sessions SET last_seen=?, expires_at=? WHERE token_hash=?",
            (now, now + _ttl_seconds(), th),
        )
        return _public(u)


def destroy_session(token: str) -> None:
    if not token:
        return
    with _conn() as con:
        con.execute("DELETE FROM sessions WHERE token_hash=?",
                    (_hash_token(token),))


def purge_expired() -> int:
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM sessions WHERE expires_at IS NOT NULL AND expires_at < ?",
            (time.time(),))
        return cur.rowcount or 0
