#!/usr/bin/env bash
# =============================================================================
# build-repo.sh — Gera um repositório APT AUTOCONTIDO do Mundix Security 360.
#
# O repo inclui o .deb do Mundix E todo o fecho de dependências (.debs do
# bundle, incluindo ClickHouse) — o alvo não precisa de nenhum outro repo de
# terceiros. Metadados assinados com uma chave GPG própria do repositório
# (gerada no primeiro uso, fica no keyring do root — fora do pacote).
#
# Pré-requisito: rodar build-bundle.sh e build-deb.sh antes (artefatos em dist/).
#
# Uso:  sudo ./build-repo.sh
# Saída: installer/dist/repo/  (publique esse diretório num HTTP estático)
# =============================================================================
set -euo pipefail

INSTALLER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${INSTALLER_DIR}/lib/common.sh"
# shellcheck source=manifest.env
source "${INSTALLER_DIR}/manifest.env"

require_root
OUT="${INSTALLER_DIR}/dist"
REPO="${OUT}/repo"
KEY_NAME="Mundix Security 360 (repo APT) <repo@mundix360.local>"

BUNDLE="$(ls -t "${OUT}"/mundix-appliance-*.tar.zst 2>/dev/null | head -1 || true)"
[[ -n "${BUNDLE}" ]] || die "bundle não encontrado — rode build-bundle.sh antes."
DEB="$(ls -t "${OUT}"/mundix360_*_all.deb 2>/dev/null | head -1 || true)"
[[ -n "${DEB}" ]] || die "pacote .deb não encontrado — rode build-deb.sh antes."

WORK="$(mktemp -d)"; trap 'rm -rf "${WORK}"' EXIT

# ------------------------------------------------------------------ pool -----
step "Pool de pacotes (mundix360 + fecho de dependências do bundle)"
rm -rf "${REPO}"
mkdir -p "${REPO}/pool/main" "${REPO}/dists/stable/main/binary-all"
tar --zstd -xf "${BUNDLE}" -C "${WORK}" mundix-appliance/bundle/debs
cp "${WORK}"/mundix-appliance/bundle/debs/*.deb "${REPO}/pool/main/"
rm -f "${REPO}/pool/main/Packages"
cp "${DEB}" "${REPO}/pool/main/"
ok "$(ls "${REPO}/pool/main"/*.deb | wc -l) pacotes no pool"

# --------------------------------------------------------------- metadados ---
step "Packages + Release"
( cd "${REPO}" && dpkg-scanpackages --arch all pool/main > "dists/stable/main/binary-all/Packages" 2>/dev/null )
( cd "${REPO}" && gzip -9kf "dists/stable/main/binary-all/Packages" )
cat > "${WORK}/release.conf" <<EOF
APT::FTPArchive::Release::Origin "Mundix";
APT::FTPArchive::Release::Label "Mundix Security 360";
APT::FTPArchive::Release::Suite "stable";
APT::FTPArchive::Release::Codename "stable";
APT::FTPArchive::Release::Architectures "all";
APT::FTPArchive::Release::Components "main";
APT::FTPArchive::Release::Description "Repositório APT do appliance Mundix Security 360";
EOF
( cd "${REPO}" && apt-ftparchive -c "${WORK}/release.conf" release dists/stable > dists/stable/Release )
ok "metadados gerados"

# -------------------------------------------------------------- assinatura ---
step "Assinatura GPG do repositório"
if ! gpg --batch --list-secret-keys "${KEY_NAME}" >/dev/null 2>&1; then
  log "gerando chave do repositório (fica no keyring do root)"
  gpg --batch --pinentry-mode loopback --passphrase '' \
      --quick-generate-key "${KEY_NAME}" rsa4096 sign never
fi
gpg --batch --yes --pinentry-mode loopback -u "${KEY_NAME}" \
    --digest-algo SHA512 --sign --armor \
    --output "${REPO}/dists/stable/InRelease" "${REPO}/dists/stable/Release"
gpg --batch --yes --pinentry-mode loopback -u "${KEY_NAME}" \
    --digest-algo SHA512 --detach-sign --armor \
    --output "${REPO}/dists/stable/Release.gpg" "${REPO}/dists/stable/Release"
gpg --batch --yes --armor --export "${KEY_NAME}" > "${REPO}/mundix-repo.gpg"
ok "repo assinado; chave pública em repo/mundix-repo.gpg"

cat <<EOF

Repositório pronto em: ${REPO}

Para publicar e usar:
  1) Hospede o diretório repo/ num HTTP estático (ex.: nesta caixa:
       mundix-export start   # e aponte o subdiretório /repo/ — ou use nginx)
  2) No alvo:
       curl -fsSL <URL>/mundix-repo.gpg | sudo gpg --dearmor -o /usr/share/keyrings/mundix-repo.gpg
       echo "deb [signed-by=/usr/share/keyrings/mundix-repo.gpg] <URL> stable main" | sudo tee /etc/apt/sources.list.d/mundix360.list
       sudo apt update && sudo apt install mundix360

A chave PRIVADA fica no keyring GPG do root desta build box — guarde-a
(exporte com: gpg --export-secret-keys '${KEY_NAME}' > repo-privada.asc)
EOF
