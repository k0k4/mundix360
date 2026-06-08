#!/usr/bin/env bash
# Fase 20 — Código do Mundix: posiciona o repositório e instala as units canônicas.

phase_mundix() {
  step "Aplicação Mundix"

  # O código vem extraído junto do bundle (em SRC_ROOT). Se ainda não estiver
  # em MUNDIX_ROOT, copia para lá (exceto o diretório bundle/, que é pesado e
  # só serve à instalação). Na build box de dev, SRC_ROOT == MUNDIX_ROOT (no-op).
  local src_root; src_root="$(cd "${INSTALLER_DIR}/.." && pwd)"
  if [[ "${src_root}" != "${MUNDIX_ROOT}" ]]; then
    log "instalando código em ${MUNDIX_ROOT}"
    run install -d -m 0755 "${MUNDIX_ROOT}"
    local item base
    for item in "${src_root}"/*; do
      base="$(basename "${item}")"
      [[ "${base}" == "bundle" ]] && continue
      run cp -a "${item}" "${MUNDIX_ROOT}/"
    done
  fi

  # O código já deve estar em MUNDIX_ROOT (copiado acima ou via git clone).
  [[ -d "${MUNDIX_ROOT}/dashboard/backend/app" ]] \
    || die "código não encontrado em ${MUNDIX_ROOT} (descompacte o bundle antes)."
  ok "código em ${MUNDIX_ROOT}"

  # Diretórios de estado.
  local d
  for d in "${MUNDIX_STATE_DIRS[@]}"; do
    run install -d -m 0750 "$d"
  done

  # Units canônicas do perfil núcleo.
  local u
  for u in "${MUNDIX_UNITS[@]}"; do
    run install -m 0644 "${INSTALLER_DIR}/units/${u}" "/etc/systemd/system/${u}"
    log "unit instalada: ${u}"
  done

  # Remove drop-ins legados que apontavam para portas/serviços antigos.
  if [[ -d /etc/systemd/system/mundix-dashboard-api.service.d ]]; then
    run rm -rf /etc/systemd/system/mundix-dashboard-api.service.d
  fi

  run systemctl daemon-reload
  ok "units do Mundix aplicadas"
}
