#!/usr/bin/env bash
# =============================================================================
# Mundix Security 360 — Export temporário de artefatos via HTTP
#
# Sobe um servidor HTTP read-only expondo installer/dist/ (ISO, bundle,
# checksums) e abre a porta no nftables. No 'stop', derruba o servidor e
# remove a regra — o firewall volta exatamente ao que era.
#
# Uso:
#   mundix-export start [porta]   # padrão 8642
#   mundix-export stop
#   mundix-export status
#
# O servidor roda como unit transitória do systemd (mundix-export.service) —
# nada sobrevive a um reboot: nem o servidor nem a regra (runtime do nft).
# =============================================================================
set -euo pipefail

EXPORT_DIR="/opt/mundix360/installer/dist"
DEFAULT_PORT=8642
UNIT="mundix-export"
NFT_COMMENT="mundix-export"

ok()   { echo "[ OK ] $*"; }
warn() { echo "[AVISO] $*" >&2; }
die()  { echo "[ERRO] $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "rode como root (sudo mundix-export $*)"

port_in_use() { ss -ltn 2>/dev/null | grep -q ":${1} "; }

# Handle da regra marcada com nosso comment (vazio se não existir).
nft_handle() {
  nft -a list chain inet filter input 2>/dev/null \
    | grep "comment \"${NFT_COMMENT}\"" | grep -oP 'handle \K[0-9]+' | head -1
}

fw_open() {
  local port="$1"
  [[ -n "$(nft_handle)" ]] && return 0
  # insert (topo da chain): a chain input termina com regra de log+drop,
  # então 'add' no fim nunca casaria.
  nft insert rule inet filter input tcp dport "$port" accept comment "${NFT_COMMENT}"
  ok "firewall: porta ${port}/tcp aberta (regra temporária)"
}

fw_close() {
  local h; h="$(nft_handle)"
  if [[ -n "$h" ]]; then
    nft delete rule inet filter input handle "$h"
    ok "firewall: regra temporária removida"
  fi
}

list_urls() {
  local port="$1"
  ip -4 -o addr show scope global 2>/dev/null | awk '{split($4,a,"/"); print a[1]}' \
    | while read -r ip; do echo "    http://${ip}:${port}/"; done
}

do_start() {
  local port="${1:-$DEFAULT_PORT}"
  [[ "$port" =~ ^[0-9]+$ ]] && (( port >= 1024 && port <= 65535 )) \
    || die "porta inválida: $port (use 1024-65535)"
  [[ -d "$EXPORT_DIR" ]] || die "diretório não existe: $EXPORT_DIR"

  if systemctl is-active --quiet "$UNIT" 2>/dev/null; then
    warn "export já está no ar:"; do_status; exit 0
  fi
  port_in_use "$port" && die "porta $port já está em uso por outro processo."

  systemd-run --unit="$UNIT" --quiet \
    --description="Mundix export HTTP temporário (porta ${port})" \
    /usr/bin/python3 -m http.server "$port" --bind 0.0.0.0 --directory "$EXPORT_DIR"
  echo "$port" > /run/mundix-export.port
  fw_open "$port"

  echo
  ok "export no ar — artefatos disponíveis em:"
  list_urls "$port"
  echo
  echo "  Quando terminar o download:  mundix-export stop"
}

do_stop() {
  local was_active=0
  rm -f /run/mundix-export.port
  if systemctl is-active --quiet "$UNIT" 2>/dev/null || systemctl cat "$UNIT" >/dev/null 2>&1; then
    systemctl stop "$UNIT" 2>/dev/null || true
    systemctl reset-failed "$UNIT" 2>/dev/null || true
    was_active=1
  fi
  fw_close
  if [[ "$was_active" == "1" || -n "$(nft_handle)" ]]; then
    ok "export encerrado — servidor parado e firewall como estava."
  else
    echo "export já estava parado."
  fi
}

do_status() {
  if systemctl is-active --quiet "$UNIT" 2>/dev/null; then
    local pid port
    pid="$(systemctl show -p MainPID --value "$UNIT" 2>/dev/null)"
    port="$(ss -ltnp 2>/dev/null | grep "pid=${pid}," | grep -oP ':\K[0-9]+(?= )' | head -1 || true)"
    [[ -z "$port" && -r /run/mundix-export.port ]] && port="$(cat /run/mundix-export.port)"
    echo "export: ATIVO (porta ${port:-?})"
    [[ -n "$(nft_handle)" ]] && echo "firewall: regra temporária presente" || warn "regra do firewall AUSENTE"
    echo "URLs:"
    list_urls "${port:-$DEFAULT_PORT}"
    echo "Arquivos expostos:"
    ls -lh "$EXPORT_DIR" 2>/dev/null | awk 'NR>1{printf "    %-10s %s\n", $5, $9}'
  else
    echo "export: parado"
    [[ -n "$(nft_handle)" ]] && warn "há uma regra temporária órfã no firewall — rode: mundix-export stop"
  fi
  return 0
}

case "${1:-}" in
  start)  do_start "${2:-}" ;;
  stop)   do_stop ;;
  status) do_status ;;
  *) echo "uso: mundix-export start [porta] | stop | status"; exit 2 ;;
esac
