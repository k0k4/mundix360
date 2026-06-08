#!/usr/bin/env bash
# Fase 00 — Pré-voo: valida ambiente antes de tocar no sistema.
phase_preflight() {
  step "Pré-voo"
  require_root

  # SO suportado.
  local id ver
  id="$(. /etc/os-release && echo "$ID")"
  ver="$(. /etc/os-release && echo "$VERSION_ID")"
  if [[ "$id" != "$TARGET_OS_ID" || "$ver" != "$TARGET_OS_VERSION" ]]; then
    warn "SO detectado: ${id} ${ver} (suportado: ${TARGET_OS_ID} ${TARGET_OS_VERSION})"
    confirm "Continuar mesmo assim?" || die "abortado pelo operador."
  else
    ok "SO ${id} ${ver}"
  fi

  # Arquitetura.
  local arch; arch="$(dpkg --print-architecture)"
  [[ "$arch" == "amd64" ]] || warn "arquitetura ${arch} não testada (esperado amd64)."

  # Espaço em disco (>= 4 GB livres em /).
  local free_kb; free_kb="$(df --output=avail / | tail -1 | tr -d ' ')"
  if (( free_kb < 4194304 )); then
    warn "pouco espaço livre em / ($(( free_kb / 1024 )) MB). Recomendado >= 4 GB."
  else
    ok "disco: $(( free_kb / 1024 / 1024 )) GB livres"
  fi

  # Modo de instalação (offline exige bundle).
  if [[ "${MODE}" == "offline" ]]; then
    [[ -d "${BUNDLE_DIR}/debs" ]] || die "modo offline mas bundle não encontrado em ${BUNDLE_DIR}."
    ok "bundle offline: ${BUNDLE_DIR}"
  else
    ok "modo online (instala via apt da internet)"
  fi
}
