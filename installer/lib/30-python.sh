#!/usr/bin/env bash
# Fase 30 — Ambiente Python (venv a partir de wheels do bundle, ou online).

phase_python() {
  step "Ambiente Python"

  if [[ ! -d "${MUNDIX_VENV}" ]]; then
    run python3 -m venv "${MUNDIX_VENV}"
    ok "venv criado em ${MUNDIX_VENV}"
  fi

  local req="${MUNDIX_ROOT}/dashboard/backend/requirements.txt"
  [[ -f "$req" ]] || die "requirements.txt não encontrado."

  if [[ "${MODE}" == "offline" ]]; then
    local wheels="${BUNDLE_DIR}/wheels"
    [[ -d "$wheels" ]] || die "wheels não encontrados no bundle (${wheels})."
    run "${MUNDIX_VENV}/bin/pip" install --no-index --find-links "$wheels" -r "$req"
  else
    run "${MUNDIX_VENV}/bin/pip" install --upgrade pip
    run "${MUNDIX_VENV}/bin/pip" install -r "$req"
  fi
  ok "dependências Python instaladas"
}
