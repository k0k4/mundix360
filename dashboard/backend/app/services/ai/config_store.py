"""Runtime-editable AI configuration, persisted in the AI SQLite DB.

Effective config = environment/`settings` defaults overridden by operator-set
values stored in the `ai_config` table. Secrets are handled with care:

- `api_key` is stored in clear text (product decision: write-only field in the UI,
  DB file is root-only and gitignored). It is never returned to the UI.
- the master password is **never** stored in clear text — only a PBKDF2 hash.

A small in-memory cache avoids hitting SQLite on every `redact()`/`effective()`
call; it is invalidated whenever the config is written.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time
from typing import Any

from ...config import settings
from . import memory

# Provider presets surfaced in the UI (base_url + suggested models).
PRESETS: list[dict[str, Any]] = [
    {
        "id": "dashscope",
        "label": "Alibaba DashScope (Qwen)",
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen3.7-max", "qwen-max", "qwen-plus", "qwen-turbo"],
    },
    {
        "id": "openai",
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "o4-mini"],
    },
    {
        "id": "openrouter",
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "models": ["openai/gpt-4o", "anthropic/claude-3.5-sonnet", "qwen/qwen-2.5-72b-instruct"],
    },
    {
        "id": "custom",
        "label": "Custom (OpenAI-compatible)",
        "base_url": "",
        "models": [],
    },
]

# Keys the operator may write through PUT /config.
_PLAIN_KEYS = {"base_url", "model", "custom_instructions"}
_INT_KEYS = {"max_tokens", "max_tool_iters", "request_timeout"}
_FLOAT_KEYS = {"temperature"}
_BOOL_KEYS = {"masking_enabled"}
# Changing any of these is treated as a privileged/security-sensitive action.
SENSITIVE_KEYS = {"api_key", "master_password", "masking_enabled", "base_url", "custom_instructions"}

_DEFAULT_TEMPERATURE = 0.3
_PBKDF2_ITERS = 200_000

_lock = threading.Lock()
_cache: dict[str, str] | None = None
_cache_sig: tuple[float, int] | None = None


def _db_signature() -> tuple[float, int]:
    """Cheap fingerprint of the ai.db (and its WAL) so that writes performed by
    a separate process — e.g. the ``app.admin`` recovery CLI run while the API
    is live — are detected and the in-memory cache reloaded. Uses the newest
    mtime/size across the main db and its ``-wal`` sidecar."""
    sig_mtime = 0.0
    sig_size = 0
    for suffix in ("", "-wal"):
        try:
            st = os.stat(f"{settings.ai_db_path}{suffix}")
        except OSError:
            continue
        sig_mtime = max(sig_mtime, st.st_mtime)
        sig_size += st.st_size
    return (sig_mtime, sig_size)


# --- low-level cache -------------------------------------------------------
def _load() -> dict[str, str]:
    global _cache, _cache_sig
    with _lock:
        sig = _db_signature()
        if _cache is None or sig != _cache_sig:
            try:
                with memory._conn() as con:
                    rows = con.execute("SELECT key, value FROM ai_config").fetchall()
                _cache = {r["key"]: r["value"] for r in rows}
                _cache_sig = _db_signature()
            except Exception:
                # Fail open with no overrides rather than break the agent/redaction.
                return {}
        return dict(_cache)


def invalidate() -> None:
    global _cache, _cache_sig
    with _lock:
        _cache = None
        _cache_sig = None


def _write(key: str, value: str | None) -> None:
    with memory._conn() as con:
        if value is None:
            con.execute("DELETE FROM ai_config WHERE key=?", (key,))
        else:
            con.execute(
                "INSERT INTO ai_config (key, value, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, value, time.time()),
            )


# --- password hashing ------------------------------------------------------
def _hash_password(plain: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt, _PBKDF2_ITERS)
    return f"pbkdf2_sha256${_PBKDF2_ITERS}${salt.hex()}${dk.hex()}"


def _verify_hash(plain: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", plain.encode(), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# --- master password -------------------------------------------------------
def master_password_set() -> bool:
    return bool(_load().get("master_password_hash") or settings.ai_master_password)


def master_password_source() -> str:
    if _load().get("master_password_hash"):
        return "db"
    if settings.ai_master_password:
        return "env"
    return "none"


def set_master_password(plain: str) -> None:
    _write("master_password_hash", _hash_password(plain))
    invalidate()


def clear_master_password() -> None:
    """Remove the stored master-password hash. After this, sensitive config
    changes no longer require a current password, so a new one can be set from
    the UI. Intended for local root recovery only (see app.admin)."""
    _write("master_password_hash", None)
    invalidate()


def verify_master_password(candidate: str) -> bool:
    if not candidate:
        return False
    stored = _load().get("master_password_hash")
    if stored:
        return _verify_hash(candidate, stored)
    if settings.ai_master_password:
        return hmac.compare_digest(str(candidate), str(settings.ai_master_password))
    return False


# --- effective config ------------------------------------------------------
def effective() -> dict[str, Any]:
    db = _load()
    temp = db.get("temperature")
    return {
        "base_url": db.get("base_url") or settings.ai_base_url,
        "model": db.get("model") or settings.ai_model,
        "api_key": db.get("api_key") or settings.dashscope_api_key,
        "request_timeout": int(db.get("request_timeout") or settings.ai_request_timeout),
        "max_tokens": int(db.get("max_tokens") or settings.ai_max_tokens),
        "max_tool_iters": int(db.get("max_tool_iters") or settings.ai_max_tool_iters),
        "temperature": float(temp) if temp not in (None, "") else _DEFAULT_TEMPERATURE,
        "masking_enabled": db.get("masking_enabled", "1") != "0",
        "custom_instructions": db.get("custom_instructions") or "",
    }


def live_secrets() -> list[str]:
    """Clear-text secrets to scrub from any text (defence in depth).

    Read from the in-memory cache, never SQLite-per-call. The master password is
    hashed (not here); only the env master password (if any) is clear text."""
    db = _load()
    vals = [db.get("api_key") or settings.dashscope_api_key, settings.ai_master_password]
    return [v for v in vals if v and len(v) >= 6]


def public_config() -> dict[str, Any]:
    """Config for the UI — never includes secret values."""
    e = effective()
    db = _load()
    return {
        "base_url": e["base_url"],
        "model": e["model"],
        "request_timeout": e["request_timeout"],
        "max_tokens": e["max_tokens"],
        "max_tool_iters": e["max_tool_iters"],
        "temperature": e["temperature"],
        "masking_enabled": e["masking_enabled"],
        "custom_instructions": e["custom_instructions"],
        "api_key_set": bool(e["api_key"]),
        "api_key_source": "db" if db.get("api_key") else ("env" if settings.dashscope_api_key else "none"),
        "master_password_set": master_password_set(),
        "master_password_source": master_password_source(),
        "presets": PRESETS,
    }


# --- writes ----------------------------------------------------------------
def apply_updates(updates: dict[str, Any]) -> list[str]:
    """Validate + persist a partial config update. Returns the list of changed keys.

    Secrets (`api_key`, `master_password`) are only updated when a non-empty value
    is supplied. Raises ValueError on invalid input.
    """
    changed: list[str] = []

    for k, v in updates.items():
        if k in _PLAIN_KEYS:
            sval = "" if v is None else str(v)
            if k == "base_url" and sval:
                if not (sval.startswith("http://") or sval.startswith("https://")):
                    raise ValueError("base_url deve começar com http:// ou https://")
            if k == "custom_instructions" and len(sval) > 8000:
                raise ValueError("instruções do operador muito longas (máx 8000)")
            _write(k, sval or None)
            changed.append(k)
        elif k in _INT_KEYS:
            iv = int(v)
            bounds = {
                "max_tokens": (64, 32768),
                "max_tool_iters": (0, 500),
                "request_timeout": (5, 600),
            }[k]
            if not (bounds[0] <= iv <= bounds[1]):
                raise ValueError(f"{k} fora do intervalo {bounds}")
            _write(k, str(iv))
            changed.append(k)
        elif k in _FLOAT_KEYS:
            fv = float(v)
            if not (0.0 <= fv <= 2.0):
                raise ValueError("temperature deve estar entre 0.0 e 2.0")
            _write(k, str(fv))
            changed.append(k)
        elif k in _BOOL_KEYS:
            _write(k, "1" if v else "0")
            changed.append(k)
        elif k == "api_key":
            if v:  # write-only: ignore empty (keeps existing)
                _write("api_key", str(v))
                changed.append("api_key")
        elif k == "master_password":
            if v:
                set_master_password(str(v))
                changed.append("master_password")
        # unknown keys are ignored

    invalidate()
    return changed
