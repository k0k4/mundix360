"""Chamados (tickets): trilha durável e transparente de alterações de código da IA.

Toda modificação de código-fonte que a IA aplica (pelo portão de senha master ou
por uma sessão admin) é registrada aqui como um "chamado": um registro auditável
que o operador acompanha e que a própria IA pode revisar (ferramenta
``list_tickets``). É gravado como um arquivo JSONL (uma linha por chamado) no
diretório de dados da appliance — dado de runtime, fora do git.

O arquivo é a fonte da verdade e é legível por humanos; as funções abaixo apenas
acrescentam (append-only, nunca reescrevem) e leem para a UI / para a IA.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

from ...config import settings


def _path() -> str:
    """Caminho do arquivo de chamados, ao lado do ai.db (diretório de dados)."""
    return os.path.join(os.path.dirname(settings.ai_db_path), "chamados.jsonl")


def record_code_change(
    *,
    path: str,
    description: str,
    actor: str,
    action: str = "edit",
    commit: str | None = None,
    committed: bool = False,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """Abre e persiste um chamado para uma alteração de código aplicada."""
    ticket = {
        "id": uuid.uuid4().hex[:12],
        "created_at": time.time(),
        "type": "code_change",
        "status": "applied",
        "actor": actor or "operator",
        "path": path,
        "action": action,
        "description": (description or "").strip()[:1000],
        "commit": commit,
        "committed": bool(committed),
        "conversation_id": conversation_id,
    }
    p = _path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(ticket, ensure_ascii=False) + "\n")
    return ticket


def list_tickets(limit: int = 50) -> list[dict[str, Any]]:
    """Chamados mais recentes primeiro (lê o JSONL inteiro; arquivo é pequeno)."""
    p = _path()
    if not os.path.isfile(p):
        return []
    out: list[dict[str, Any]] = []
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    out.sort(key=lambda t: t.get("created_at", 0), reverse=True)
    return out[: max(1, min(int(limit or 50), 500))]
