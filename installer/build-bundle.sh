#!/usr/bin/env bash
# =============================================================================
# build-bundle.sh — Gera o pacote OFFLINE do appliance Mundix Security 360.
#
# Rode numa "build box" Ubuntu 24.04 COM internet (idealmente idêntica ao alvo).
# Produz:  dist/mundix-appliance-<versao>.tar.zst
# Conteúdo: código + .debs (com dependências) + wheels Python + frontend dist
#           + o próprio instalador. O minipc instala 100% offline a partir dele.
#
# Uso:  sudo ./build-bundle.sh
# =============================================================================
set -euo pipefail

INSTALLER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${INSTALLER_DIR}/.." && pwd)"
source "${INSTALLER_DIR}/lib/common.sh"
source "${INSTALLER_DIR}/manifest.env"

require_root
WORK="$(mktemp -d)"
STAGE="${WORK}/mundix-appliance"
OUT="${INSTALLER_DIR}/dist"
trap 'rm -rf "${WORK}"' EXIT

step "1/6 — Estrutura do bundle"
mkdir -p "${STAGE}/bundle/debs" "${STAGE}/bundle/wheels" "${STAGE}/bundle/frontend-dist"
mkdir -p "${OUT}"

step "2/6 — Baixando pacotes .deb (fecho completo de dependências)"
# Resolve TODA a árvore de dependências (independente do que já está instalado
# nesta build box) e baixa cada .deb. Pacotes virtuais falham e são ignorados.
# Um repositório de terceiros quebrado nesta build box não deve abortar o bundle.
apt-get update 2>/dev/null || warn "apt-get update com avisos (repos de terceiros) — seguindo com as listas em cache."
mapfile -t CLOSURE < <(
  apt-cache depends --recurse --no-recommends --no-suggests \
    --no-conflicts --no-breaks --no-replaces --no-enhances --no-pre-depends \
    "${APT_PACKAGES[@]}" 2>/dev/null | grep -E '^[a-zA-Z0-9]' | sort -u
)
log "fecho de dependências: ${#CLOSURE[@]} pacotes"
(
  cd "${STAGE}/bundle/debs"
  for p in "${CLOSURE[@]}"; do
    apt-get download "$p" 2>/dev/null || true
  done
)
( cd "${STAGE}/bundle/debs" && dpkg-scanpackages -m . > Packages 2>/dev/null || true )
ok "$(ls "${STAGE}/bundle/debs"/*.deb 2>/dev/null | wc -l) .debs baixados"

step "3/6 — Baixando wheels Python"
pip3 download -d "${STAGE}/bundle/wheels" -r "${REPO_ROOT}/dashboard/backend/requirements.txt"
ok "$(ls "${STAGE}/bundle/wheels" | wc -l) artefatos Python"

step "4/6 — Buildando o frontend (dist pré-compilado)"
if command -v npm >/dev/null; then
  ( cd "${REPO_ROOT}/dashboard/frontend" && npm ci --no-audit --no-fund && npm run build )
  cp -a "${REPO_ROOT}/dashboard/frontend/dist/." "${STAGE}/bundle/frontend-dist/"
  ok "frontend buildado"
else
  warn "npm ausente — bundle sairá SEM frontend-dist (instale node e rode de novo)."
fi

step "5/6 — Copiando código + instalador (sem dados/segredos)"
rsync -a --delete \
  --exclude '.git' --exclude 'node_modules' --exclude 'data' --exclude 'logs' \
  --exclude 'secrets' --exclude 'backups' --exclude 'bin' \
  --filter='+ /installer/manifest.env' --filter='+ *.env.example' --filter='- *.env' \
  --exclude '*.db' --exclude '__pycache__' \
  --exclude '/bundle' \
  --exclude 'installer/dist' --exclude 'installer/bundle' \
  "${REPO_ROOT}/" "${STAGE}/"
# Garante o dist dentro do código também (para a fase frontend).
mkdir -p "${STAGE}/dashboard/frontend/dist"
cp -a "${STAGE}/bundle/frontend-dist/." "${STAGE}/dashboard/frontend/dist/" 2>/dev/null || true
# Exemplo de env (sem segredos) para o seed.
[[ -f "${REPO_ROOT}/configs/openrouter.env.example" ]] \
  || echo 'OPENROUTER_API_KEY=' > "${STAGE}/configs/openrouter.env.example"

step "6/6 — Empacotando (.tar.zst)"
ARCHIVE="${OUT}/mundix-appliance-${MUNDIX_VERSION}.tar.zst"
tar -C "${WORK}" -cf - mundix-appliance | zstd -19 -T0 -o "${ARCHIVE}" -f
ok "bundle: ${ARCHIVE} ($(du -h "${ARCHIVE}" | cut -f1))"

cat <<EOF

Próximos passos:
  1. Copie ${ARCHIVE} para o minipc (pendrive/scp).
  2. No minipc:  tar --zstd -xf $(basename "${ARCHIVE}") && cd mundix-appliance/installer
  3.             sudo ./install.sh        # instalação offline + assistente inicial
EOF
