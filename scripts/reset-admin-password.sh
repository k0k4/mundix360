#!/usr/bin/env bash
# Mundix Security 360 — Recuperação de acesso ao painel (login web).
#
# Irmão do reset-master-password.sh, mas para a SENHA DE LOGIN do dashboard
# (tabela users do auth.db) — a senha mestra é só da IA e não destrava o login
# (ex.: após restaurar um backup de outra máquina). Usa `app.admin
# reset-password`, que redefine a senha, REATIVA a conta e REVOGA as sessões;
# se o usuário não existir, oferece criá-lo como administrador.
#
# A senha é digitada num prompt OCULTO (getpass dentro do Python, com
# confirmação) e nunca vira argumento de comando — não fica no histórico do
# shell, em logs nem na lista de processos.
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
echo "== Recuperação de acesso ao painel (login web) =="
read -rp "Usuário do painel [admin]: " user
user="${user:-admin}"

# O prompt oculto e a confirmação acontecem dentro do Python (getpass usa
# /dev/tty, então funciona mesmo com a saída capturada abaixo).
out=""
if out="$("$PY" -m app.admin reset-password "$user" 2>&1)"; then
  echo "$out"
  echo "Pronto: conta ativa e sessões antigas revogadas. Já é possível entrar no painel."
  exit 0
fi
echo "$out" >&2

if grep -q "não encontrado" <<<"$out"; then
  echo
  read -rp "O usuário '$user' não existe. Criar agora como administrador? [s/N] " c
  if [[ "${c,,}" =~ ^(s|sim)$ ]]; then
    "$PY" -m app.admin create-admin "$user"
    echo "Pronto: administrador '$user' criado e ativo. Já é possível entrar no painel."
    exit 0
  fi
fi
echo "Nada foi alterado." >&2
exit 1
