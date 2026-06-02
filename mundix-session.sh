#!/bin/bash
# Mundix Security 360 — Persistent Session Script
# Uso: /opt/mundix360/mundix-session.sh

SESSION="mundix-dev"
WORKDIR="/opt/mundix360"

if ! command -v tmux &>/dev/null; then
  echo "Instalando tmux..."
  sudo apt update && sudo apt install -y tmux
fi

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "Sessão '$SESSION' já existe. Reconectando..."
  tmux attach -t "$SESSION"
else
  echo "Criando sessão '$SESSION'..."
  tmux new-session -d -s "$SESSION" -c "$WORKDIR"
  tmux send-keys -t "$SESSION" "echo 'Mundix Security 360 — dev session'" Enter
  tmux send-keys -t "$SESSION" "opencode" Enter
  tmux attach -t "$SESSION"
fi
