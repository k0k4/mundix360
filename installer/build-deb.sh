#!/usr/bin/env bash
# =============================================================================
# build-deb.sh — Gera o pacote .deb do Mundix Security 360.
#
# Pacote "online": o payload é o código + frontend dist; as dependências de
# sistema são declaradas no Depends (resolvidas via APT — inclusive do nosso
# repo autocontido gerado pelo build-repo.sh). O postinst roda o instalador
# completo (mundix-install.sh --skip-apt --skip-frontend).
#
# Uso:  sudo ./build-deb.sh
# Saída:  installer/dist/mundix360-<versao>-1_all.deb
# =============================================================================
set -euo pipefail

INSTALLER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${INSTALLER_DIR}/.." && pwd)"
# shellcheck source=lib/common.sh
source "${INSTALLER_DIR}/lib/common.sh"
# shellcheck source=manifest.env
source "${INSTALLER_DIR}/manifest.env"

OUT="${INSTALLER_DIR}/dist"
mkdir -p "${OUT}"

WORK="$(mktemp -d)"; trap 'rm -rf "${WORK}"' EXIT
PKG="mundix360_${MUNDIX_VERSION}-1_all"
STAGE="${WORK}/${PKG}"
mkdir -p "${STAGE}/DEBIAN" "${STAGE}/opt/mundix360"

# ---------------------------------------------------------------- payload ----
step "Payload (/opt/mundix360, sem dados/segredos/artefatos de build)"
rsync -a \
  --exclude '.git' --exclude 'node_modules' --exclude 'data' --exclude 'logs' \
  --exclude 'secrets' --exclude 'backups' --exclude 'bin' --exclude 'env_bkp' \
  --filter='+ /installer/manifest.env' --filter='+ *.env.example' --filter='- *.env' \
  --exclude '*.db' --exclude '__pycache__' \
  --exclude 'installer/dist' --exclude 'installer/bundle' --exclude 'installer/keys' \
  "${REPO_ROOT}/" "${STAGE}/opt/mundix360/"
[[ -f "${STAGE}/opt/mundix360/dashboard/frontend/dist/index.html" ]] \
  || die "frontend dist ausente no payload (rode um build do frontend antes)."

# ---------------------------------------------------------------- DEBIAN -----
step "Metadados do pacote"
DEPS="$(printf '%s, ' "${APT_PACKAGES[@]}")"; DEPS="${DEPS%, }"
# Dados/SIEM (ClickHouse/Valkey) vão como Recommends: um Depends duro faria o
# `apt install mundix360` abortar se o postinst do ClickHouse falhar (SIGILL em
# CPU sem AVX). Com Recommends, dá para instalar com --no-install-recommends.
RECOMMENDS="$(printf '%s, ' "${APT_PACKAGES_NONCRIT[@]}")"; RECOMMENDS="${RECOMMENDS%, }"
sed -e "s/@VERSION@/${MUNDIX_VERSION}/g" -e "s/@DEPS@/${DEPS}/g" \
    -e "s/@RECOMMENDS@/${RECOMMENDS}/g" \
  "${INSTALLER_DIR}/deb/control" > "${STAGE}/DEBIAN/control"
for s in postinst prerm postrm; do
  install -m 0755 "${INSTALLER_DIR}/deb/${s}" "${STAGE}/DEBIAN/${s}"
done
grep -E '^(Package|Version|Architecture):' "${STAGE}/DEBIAN/control"

# ---------------------------------------------------------------- build ------
step "Empacotando"
DEB_OUT="${OUT}/${PKG}.deb"
rm -f "${DEB_OUT}"
dpkg-deb --build --root-owner-group "${STAGE}" "${DEB_OUT}"
ok "pacote: ${DEB_OUT} ($(du -h "${DEB_OUT}" | cut -f1))"

cat <<EOF

Testar local:      sudo dpkg -i '${DEB_OUT}'   (ou melhor: via repo — build-repo.sh)
Instalação via APT (depois de hospedar o repo):
  curl -fsSL <URL>/mundix-repo.gpg | sudo gpg --dearmor -o /usr/share/keyrings/mundix-repo.gpg
  echo "deb [signed-by=/usr/share/keyrings/mundix-repo.gpg] <URL> stable main" | sudo tee /etc/apt/sources.list.d/mundix360.list
  sudo apt update && sudo apt install mundix360
EOF
