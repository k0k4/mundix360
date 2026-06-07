"""Password-gated source-code editing.

The AI can only *propose* a code change. Nothing is written until the user enters
the master password in the dashboard; the password is verified here and never
passes through the LLM context.
"""
from __future__ import annotations

import difflib
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from ...config import settings
from . import config_store, safety

# pending change_id -> change dict
_PENDING: dict[str, dict[str, Any]] = {}

# brute-force protection for the confirm endpoint
_FAILS: list[float] = []
_MAX_FAILS = 5
_WINDOW = 300.0  # seconds


def propose(path: str, new_content: str, description: str) -> dict[str, Any]:
    """Register a pending code change and return its id + server-computed diff."""
    if not safety.in_editable_root(path):
        raise ValueError("caminho fora da raiz editável do projeto")
    if safety.is_secret_path(path):
        raise ValueError("não é permitido editar arquivos de segredo")
    real = safety.resolve_in_root(path)
    # block binaries / git internals
    if "/.git/" in real or real.endswith((".db", ".sqlite", ".png", ".jpg", ".lock")):
        raise ValueError("tipo de arquivo não editável")

    old = ""
    exists = os.path.isfile(real)
    if exists:
        with open(real, "r", encoding="utf-8", errors="replace") as f:
            old = f.read()

    diff = "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )
    cid = uuid.uuid4().hex
    _PENDING[cid] = {
        "id": cid,
        "path": real,
        "display_path": path,
        "new_content": new_content,
        "description": description,
        "exists": exists,
        "created_at": time.time(),
    }
    return {
        "id": cid,
        "path": path,
        "description": description,
        "exists": exists,
        "diff": safety.redact(diff) or "(sem alterações)",
        "added": new_content.count("\n") + 1,
    }


def get_pending(cid: str) -> dict[str, Any] | None:
    return _PENDING.get(cid)


def list_pending() -> list[dict[str, Any]]:
    return [
        {
            "id": c["id"],
            "path": c["display_path"],
            "description": c["description"],
            "exists": c["exists"],
            "created_at": c["created_at"],
        }
        for c in _PENDING.values()
    ]


def _rate_limited() -> bool:
    now = time.time()
    while _FAILS and now - _FAILS[0] > _WINDOW:
        _FAILS.pop(0)
    return len(_FAILS) >= _MAX_FAILS


def confirm(change_id: str, password: str) -> dict[str, Any]:
    """Verify the master password and apply the pending change. Raises on failure."""
    if _rate_limited():
        raise PermissionError("muitas tentativas; tente novamente em alguns minutos")
    if not config_store.master_password_set():
        raise PermissionError(
            "Senha mestra não configurada — defina-a em Mundix AI → Configuração "
            "(ou MUNDIX_AI_MASTER_PASSWORD no .env) para habilitar a edição de código"
        )
    if not safety.password_ok(password):
        _FAILS.append(time.time())
        raise PermissionError("senha master incorreta")

    change = _PENDING.get(change_id)
    if not change:
        raise KeyError("mudança pendente não encontrada ou expirada")

    real = change["path"]
    # final guard
    if not safety.in_editable_root(real) or safety.is_secret_path(real):
        raise ValueError("destino inválido")

    Path(real).parent.mkdir(parents=True, exist_ok=True)
    with open(real, "w", encoding="utf-8") as f:
        f.write(change["new_content"])

    commit = _git_commit(real, change["description"])
    _PENDING.pop(change_id, None)
    return {
        "ok": True,
        "path": change["display_path"],
        "committed": commit.get("ok", False),
        "commit": commit.get("ref"),
    }


def _git_commit(path: str, description: str) -> dict[str, Any]:
    root = settings.ai_editable_root
    try:
        subprocess.run(
            ["git", "-C", root, "add", path],
            capture_output=True, text=True, timeout=20,
        )
        msg = f"ai: {description}\n\nApplied via password-gated AI code change."
        r = subprocess.run(
            ["git", "-C", root, "commit", "-m", msg, "--", path],
            capture_output=True, text=True, timeout=20,
        )
        if r.returncode != 0:
            return {"ok": False, "ref": None}
        ref = subprocess.run(
            ["git", "-C", root, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        return {"ok": True, "ref": ref}
    except Exception:
        return {"ok": False, "ref": None}
