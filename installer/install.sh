#!/usr/bin/env bash
# =============================================================================
# Mundix Security 360 — Instalador do appliance (perfil NÚCLEO)
#
# Uso (no minipc, a partir do bundle descompactado):
#   sudo ./install.sh                 # offline (usa o bundle) — padrão
#   sudo ./install.sh --online        # instala via internet (build/dev)
#   sudo ./install.sh --dry-run       # mostra o que faria, sem alterar nada
#   sudo ./install.sh --yes           # não-interativo (gera segredos)
#   sudo ./install.sh --no-firstboot  # instala mas não roda o assistente inicial
#
# Variáveis opcionais (não-interativo):
#   MUNDIX_MASTER_PASSWORD=...  OPENROUTER_API_KEY=...
# =============================================================================
set -euo pipefail

INSTALLER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# O bundle offline fica em installer/bundle (dev) ou ../bundle (layout empacotado).
if [[ -n "${BUNDLE_DIR:-}" ]]; then
  :
elif [[ -d "${INSTALLER_DIR}/bundle/debs" ]]; then
  BUNDLE_DIR="${INSTALLER_DIR}/bundle"
else
  BUNDLE_DIR="${INSTALLER_DIR}/../bundle"
fi
MODE="offline"
DRY_RUN=0
ASSUME_YES=0
RUN_FIRSTBOOT=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --online)        MODE="online" ;;
    --offline)       MODE="offline" ;;
    --dry-run)       DRY_RUN=1 ;;
    --yes|-y)        ASSUME_YES=1 ;;
    --no-firstboot)  RUN_FIRSTBOOT=0 ;;
    -h|--help)       sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "opção desconhecida: $1" >&2; exit 2 ;;
  esac
  shift
done
export DRY_RUN ASSUME_YES MODE BUNDLE_DIR INSTALLER_DIR

# shellcheck source=lib/common.sh
source "${INSTALLER_DIR}/lib/common.sh"
# shellcheck source=manifest.env
source "${INSTALLER_DIR}/manifest.env"
for f in "${INSTALLER_DIR}"/lib/[0-9]*.sh; do source "$f"; done

printf '%s\n' "
  __  __                 _ _      _____  __  ___
 |  \/  |_   _ _ __   __| (_)_  _|___ / / /_ / _ \\
 | |\/| | | | | '_ \ / _\` | \ \/ / |_ \| '_ \ | | |
 | |  | | |_| | | | | (_| | |>  < ___) | (_) | |_| |
 |_|  |_|\__,_|_| |_|\__,_|_/_/\_\____/ \___/ \___/
        Security 360 — Appliance Installer (${MUNDIX_VERSION}, perfil ${MUNDIX_PROFILE})
"

phase_preflight
phase_apt
phase_mundix
phase_python
phase_frontend
phase_config
phase_services
if [[ "${RUN_FIRSTBOOT}" == "1" ]]; then
  phase_firstboot
else
  warn "first-boot pulado (--no-firstboot). Rode o assistente depois para gerar identidade."
fi

step "Concluído"
ok "Mundix Security 360 instalado (perfil ${MUNDIX_PROFILE}, modo ${MODE})."
