"""Ativação de mudanças de código aplicadas: rebuild da SPA / restart da API.

Aplicar uma mudança grava + commita o fonte, mas a appliance em execução serve um
bundle de frontend PRÉ-BUILDADO (dist/) e um processo uvicorn de vida longa — então
editar o fonte não tem efeito visível até a mudança ser *ativada*:
  - fonte de frontend  -> rebuild do dist/ (dashboard/build.sh)   [~minutos no Atom]
  - .py de backend     -> restart do serviço da API (uvicorn, sem --reload)

Este módulo faz essa ativação em segundo plano e mantém o status (persistido em
disco para sobreviver ao restart) para o operador e a IA acompanharem
(GET /api/ai/deploy-status, ferramenta deploy_status).

Como em codegate._git_commit, usa subprocess diretamente: é operação interna
confiável da plataforma, não um comando vindo do modelo.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from typing import Any

from ...config import settings

_ROOT = settings.ai_editable_root
_BUILD = os.path.join(_ROOT, "dashboard", "build.sh")
_API_UNIT = "mundix-dashboard-api"

_lock = threading.Lock()
_building = False
_pending = False


def _state_path() -> str:
    return os.path.join(os.path.dirname(settings.ai_db_path), "deploy_state.json")


def _write_state(st: dict[str, Any]) -> None:
    try:
        p = _state_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
    except Exception:
        pass


def status() -> dict[str, Any]:
    try:
        with open(_state_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"kind": None, "status": "idle"}


def classify(display_path: str) -> str | None:
    """Decide o que ativar a partir do caminho (relativo à raiz editável)."""
    p = (display_path or "").lstrip("/")
    if p.startswith("dashboard/frontend/") and not p.startswith("dashboard/frontend/dist/"):
        return "frontend"
    if p.startswith("dashboard/backend/") and p.endswith(".py"):
        return "backend"
    return None


def _run_build() -> None:
    global _building, _pending
    while True:
        started = time.time()
        _write_state({"kind": "frontend", "status": "building",
                      "started_at": started, "log": ""})
        try:
            r = subprocess.run(
                ["bash", _BUILD],
                cwd=_ROOT, capture_output=True, text=True, timeout=1200,
            )
            tail = "\n".join((r.stdout + r.stderr).splitlines()[-40:])
            _write_state({
                "kind": "frontend",
                "status": "ok" if r.returncode == 0 else "failed",
                "started_at": started, "finished_at": time.time(),
                "returncode": r.returncode, "log": tail,
            })
        except Exception as e:  # noqa: BLE001
            _write_state({
                "kind": "frontend", "status": "failed", "started_at": started,
                "finished_at": time.time(), "log": f"erro: {e}",
            })
        with _lock:
            # Se uma nova mudança de frontend chegou durante o build, rebuilda de
            # novo para incluí-la; senão encerra.
            if _pending:
                _pending = False
                continue
            _building = False
            return


def _restart_api() -> None:
    # Reinicia logo em seguida, para que a resposta HTTP que disparou isto retorne
    # primeiro (caso contrário o cliente recebe uma conexão cortada).
    _write_state({"kind": "backend", "status": "restarting",
                  "started_at": time.time()})
    try:
        subprocess.Popen(
            ["sh", "-c", f"sleep 2; systemctl restart {_API_UNIT}"],
            start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as e:  # noqa: BLE001
        _write_state({"kind": "backend", "status": "failed", "log": f"erro: {e}"})


def activate(display_path: str) -> dict[str, Any]:
    """Ativa uma mudança recém-aplicada. Retorna {kind, status} do que iniciou."""
    kind = classify(display_path)
    if kind == "frontend":
        global _building, _pending
        with _lock:
            if _building:
                _pending = True
                return {"kind": "frontend", "status": "building"}
            _building = True
        threading.Thread(target=_run_build, daemon=True).start()
        return {"kind": "frontend", "status": "building"}
    if kind == "backend":
        _restart_api()
        return {"kind": "backend", "status": "restarting"}
    return {"kind": None, "status": "noop"}
