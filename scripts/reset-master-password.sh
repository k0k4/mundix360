#!/usr/bin/env bash
# Mundix Security 360 — Reset seguro da senha mestra da IA.
#
# Lê a nova senha num prompt OCULTO (sem eco) e grava apenas o hash
# PBKDF2-SHA256 no ai.db. A senha nunca vira argumento de comando, então não
# fica no histórico do shell nem em logs. Aplica imediatamente.
set -euo pipefail

BACKEND="/opt/mundix360/dashboard/backend"
PY="/opt/venv/bin/python"

if [[ $EUID -ne 0 ]]; then
  echo "Este comando precisa de privilégios de root. Rode com: sudo $0" >&2
  exit 1
fi

if [[ ! -x "$PY" ]]; then
  echo "ERRO: interpretador não encontrado em $PY" >&2
  exit 1
fi

cd "$BACKEND"
echo "== Reset da senha mestra da IA =="
echo "Digite a nova senha quando solicitado (a tela não mostra nada — é normal)."
echo
exec "$PY" -m app.admin reset-master-password
