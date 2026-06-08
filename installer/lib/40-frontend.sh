#!/usr/bin/env bash
# Fase 40 — Frontend. No appliance usamos o dist/ PRÉ-BUILDADO que vem no bundle
# (sem Node/npm na máquina final). No modo online, builda na hora se houver npm.

phase_frontend() {
  step "Frontend (SPA)"
  local dist="${MUNDIX_ROOT}/dashboard/frontend/dist"

  if [[ -f "${dist}/index.html" ]]; then
    ok "dist pré-buildado presente — nada a fazer"
    return 0
  fi

  if [[ "${MODE}" == "offline" ]]; then
    # O bundle deveria conter o dist. Se chegou aqui, é erro de empacotamento.
    if [[ -d "${BUNDLE_DIR}/frontend-dist" ]]; then
      run cp -a "${BUNDLE_DIR}/frontend-dist/." "${dist}/"
      ok "dist restaurado do bundle"
    else
      die "dist ausente e bundle sem frontend-dist. Rode build-bundle.sh corretamente."
    fi
  else
    command -v npm >/dev/null || die "npm não encontrado para build online do frontend."
    run bash "${MUNDIX_ROOT}/dashboard/build.sh"
    ok "frontend buildado"
  fi
}
