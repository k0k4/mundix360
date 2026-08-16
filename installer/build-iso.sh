#!/usr/bin/env bash
# =============================================================================
# build-iso.sh — Gera a ISO BOOTÁVEL e AUTOINSTALÁVEL do Mundix Security 360.
#
# Pega a ISO oficial do Ubuntu 24.04 Server, injeta o autoinstall (subiquity/
# cloud-init) + o bundle offline do Mundix, e repacka preservando o boot
# (BIOS + UEFI). Resultado: grave num pendrive, dê boot, e o appliance se
# instala sozinho — experiência pfSense.
#
# Pré-requisitos (build box): xorriso, curl/wget, zstd, e o bundle já gerado
#   por build-bundle.sh  (installer/dist/mundix-appliance-<versao>.tar.zst).
#
# Uso:
#   sudo ./build-iso.sh                       # baixa o Ubuntu ISO e monta tudo
#   sudo ./build-iso.sh --ubuntu /cam/ubuntu.iso   # usa uma ISO local
#   sudo ./build-iso.sh --bundle /cam/bundle.tar.zst
# =============================================================================
set -euo pipefail

INSTALLER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${INSTALLER_DIR}/lib/common.sh"
source "${INSTALLER_DIR}/manifest.env"

UBUNTU_VERSION="24.04.4"
UBUNTU_ISO_URL="https://releases.ubuntu.com/24.04/ubuntu-${UBUNTU_VERSION}-live-server-amd64.iso"
UBUNTU_ISO=""
BUNDLE=""
OUT="${INSTALLER_DIR}/dist"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ubuntu) UBUNTU_ISO="$2"; shift 2 ;;
    --bundle) BUNDLE="$2"; shift 2 ;;
    --out)    OUT="$2"; shift 2 ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) die "opção desconhecida: $1" ;;
  esac
done

require_root
command -v xorriso >/dev/null || die "instale xorriso (apt-get install xorriso)."
mkdir -p "${OUT}"

WORK="$(mktemp -d)"; trap 'rm -rf "${WORK}"' EXIT
SEED="${WORK}/server"; EMBED="${WORK}/mundix"; BOOT="${WORK}/boot"
mkdir -p "${SEED}" "${EMBED}" "${BOOT}/boot/grub"

# ---------------------------------------------------------------- 1) Ubuntu ISO
step "1/6 — ISO base do Ubuntu"
if [[ -z "${UBUNTU_ISO}" ]]; then
  UBUNTU_ISO="${OUT}/ubuntu-${UBUNTU_VERSION}-live-server-amd64.iso"
  if [[ ! -f "${UBUNTU_ISO}" ]]; then
    log "baixando ${UBUNTU_ISO_URL}"
    curl -fL --progress-bar -o "${UBUNTU_ISO}" "${UBUNTU_ISO_URL}" \
      || wget -O "${UBUNTU_ISO}" "${UBUNTU_ISO_URL}"
  fi
fi
[[ -f "${UBUNTU_ISO}" ]] || die "ISO do Ubuntu não encontrada: ${UBUNTU_ISO}"
ok "ISO base: ${UBUNTU_ISO}"

# ---------------------------------------------------------------- 2) Bundle
step "2/6 — Bundle offline do Mundix"
if [[ -z "${BUNDLE}" ]]; then
  BUNDLE="$(ls -t "${OUT}"/mundix-appliance-*.tar.zst 2>/dev/null | head -1 || true)"
fi
[[ -n "${BUNDLE}" && -f "${BUNDLE}" ]] \
  || die "bundle não encontrado. Rode ./build-bundle.sh primeiro (ou passe --bundle)."
log "extraindo ${BUNDLE}"
tar --zstd -xf "${BUNDLE}" -C "${WORK}"
# O tar contém o diretório mundix-appliance/ — embarcamos seu conteúdo em /cdrom/mundix.
cp -a "${WORK}/mundix-appliance/." "${EMBED}/"
[[ -d "${EMBED}/bundle/debs" ]] || die "bundle inválido (sem bundle/debs)."
ok "bundle embarcado ($(du -sh "${EMBED}" | cut -f1))"

# ---------------------------------------------------------------- 3) Seed nocloud
step "3/6 — Semente autoinstall (nocloud)"
cp "${INSTALLER_DIR}/iso/user-data" "${SEED}/user-data"
cp "${INSTALLER_DIR}/iso/meta-data" "${SEED}/meta-data"
ok "user-data + meta-data prontos"

# ---------------------------------------------------------------- 4) grub
step "4/6 — Ajustando o boot (grub) para autoinstall"
# Extrai os grub.cfg/loopback.cfg originais para edição.
xorriso -osirrox on -indev "${UBUNTU_ISO}" \
  -extract /boot/grub/grub.cfg "${BOOT}/boot/grub/grub.cfg" 2>/dev/null || true
xorriso -osirrox on -indev "${UBUNTU_ISO}" \
  -extract /boot/grub/loopback.cfg "${BOOT}/boot/grub/loopback.cfg" 2>/dev/null || true

_patch_grub() {
  local f="$1"; [[ -f "$f" ]] || return 0
  # Insere o parâmetro de autoinstall em todas as linhas 'linux ...' e zera o
  # timeout para entrar direto na instalação desatendida.
  sed -i 's#---#autoinstall ds=nocloud\\;s=/cdrom/server/ ---#g' "$f"
  sed -i 's/^set timeout=.*/set timeout=5/' "$f"
}
_patch_grub "${BOOT}/boot/grub/grub.cfg"
_patch_grub "${BOOT}/boot/grub/loopback.cfg"
ok "grub configurado para instalação desatendida"

# ---------------------------------------------------------------- 5) Repack
step "5/6 — Remasterizando a ISO (preservando BIOS+UEFI)"
ISO_OUT="${OUT}/mundix-appliance-${MUNDIX_VERSION}-amd64.iso"
# -boot_image any replay reaproveita EXATAMENTE o boot da ISO original;
# -map sobrepõe nossos arquivos (grub, seed e bundle).
MAPS=( -map "${EMBED}" /mundix -map "${SEED}" /server )
[[ -f "${BOOT}/boot/grub/grub.cfg" ]]     && MAPS+=( -map "${BOOT}/boot/grub/grub.cfg" /boot/grub/grub.cfg )
[[ -f "${BOOT}/boot/grub/loopback.cfg" ]] && MAPS+=( -map "${BOOT}/boot/grub/loopback.cfg" /boot/grub/loopback.cfg )

xorriso -indev "${UBUNTU_ISO}" -outdev "${ISO_OUT}" \
  -volid "MUNDIX_${MUNDIX_VERSION//./}" \
  -boot_image any replay \
  "${MAPS[@]}" \
  -compliance no_emul_toc
ok "ISO gerada"

# ---------------------------------------------------------------- 6) Checksum
step "6/6 — Finalizando"
( cd "${OUT}" && sha256sum "$(basename "${ISO_OUT}")" > "$(basename "${ISO_OUT}").sha256" )
ok "ISO:       ${ISO_OUT} ($(du -h "${ISO_OUT}" | cut -f1))"
ok "checksum:  ${ISO_OUT}.sha256"

cat <<EOF

Gravar no pendrive (CUIDADO: apaga o pendrive):
  sudo dd if='${ISO_OUT}' of=/dev/sdX bs=4M status=progress oflag=sync
  # ou use Rufus/balenaEtcher no Windows.

Depois: dê boot no minipc pelo pendrive. A instalação é AUTOMÁTICA e APAGA o
disco do alvo. Ao final ele reinicia, o Mundix se instala no 1º boot e o painel
fica em https://192.168.1.1 (plugue na LAN de gestão).
EOF
