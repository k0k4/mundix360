#!/usr/bin/env bash
# Funções compartilhadas por install.sh e pelos scripts de fase.
# shellcheck disable=SC2034
set -euo pipefail

# Cores (desligadas se não for TTY).
if [[ -t 1 ]]; then
  C_RESET=$'\e[0m'; C_BLUE=$'\e[34m'; C_GREEN=$'\e[32m'
  C_YELLOW=$'\e[33m'; C_RED=$'\e[31m'; C_DIM=$'\e[2m'
else
  C_RESET=""; C_BLUE=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_DIM=""
fi

log()   { printf '%s[mundix]%s %s\n' "$C_BLUE" "$C_RESET" "$*"; }
ok()    { printf '%s[ ok ]%s %s\n'   "$C_GREEN" "$C_RESET" "$*"; }
warn()  { printf '%s[warn]%s %s\n'   "$C_YELLOW" "$C_RESET" "$*" >&2; }
err()   { printf '%s[fail]%s %s\n'   "$C_RED" "$C_RESET" "$*" >&2; }
die()   { err "$*"; exit 1; }
step()  { printf '\n%s==>%s %s\n' "$C_BLUE" "$C_RESET" "$*"; }

# DRY_RUN=1 => apenas mostra o que faria.
run() {
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    printf '%s   would run:%s %s\n' "$C_DIM" "$C_RESET" "$*"
    return 0
  fi
  "$@"
}

require_root() {
  [[ "$(id -u)" == "0" ]] || die "execute como root (sudo)."
}

# Idempotência: só executa o bloco se a "marca" ainda não existe.
STATE_MARKER_DIR="/var/lib/mundix/install"
marked()   { [[ -f "${STATE_MARKER_DIR}/$1" ]]; }
mark()     { [[ "${DRY_RUN:-0}" == "1" ]] && return 0; mkdir -p "$STATE_MARKER_DIR"; date -Is >"${STATE_MARKER_DIR}/$1"; }

confirm() {
  [[ "${ASSUME_YES:-0}" == "1" ]] && return 0
  local ans
  read -rp "$1 [s/N] " ans
  [[ "$ans" =~ ^[sSyY]$ ]]
}
