#!/usr/bin/env bash
# Fase 10 — Pacotes APT (offline a partir do bundle, ou online via repositórios).

_setup_thirdparty_repos() {
  # Apenas no modo online: registra repositórios de terceiros (ex.: ClickHouse).
  # Campos separados por '|' (URLs contêm ':').
  local entry name line key
  for entry in "${APT_THIRDPARTY_REPOS[@]}"; do
    IFS='|' read -r name line key <<<"$entry"
    if [[ ! -f "/etc/apt/sources.list.d/mundix-${name}.list" ]]; then
      log "registrando repositório ${name}"
      run bash -c "curl -fsSL '${key}' | gpg --dearmor -o /usr/share/keyrings/mundix-${name}.gpg"
      run bash -c "echo 'deb [signed-by=/usr/share/keyrings/mundix-${name}.gpg] ${line}' > /etc/apt/sources.list.d/mundix-${name}.list"
    fi
  done
}

phase_apt() {
  step "Pacotes do sistema (${MODE})"

  if [[ "${MODE}" == "offline" ]]; then
    # Repositório local a partir dos .debs do bundle.
    # O índice Packages JÁ vem pronto no bundle (gerado pelo build-bundle.sh na
    # build box). Regenerar aqui é só uma garantia extra — e opcional, porque o
    # dpkg-scanpackages (pacote dpkg-dev) nem sempre existe no alvo.
    local repo="${BUNDLE_DIR}/debs"
    if command -v dpkg-scanpackages >/dev/null 2>&1; then
      run bash -c "cd '${repo}' && dpkg-scanpackages -m . > Packages 2>/dev/null"
    fi
    [[ -s "${repo}/Packages" ]] || die "índice Packages ausente em ${repo} (bundle incompleto)."
    run bash -c "echo 'deb [trusted=yes] file:${repo} ./' > /etc/apt/sources.list.d/mundix-bundle.list"
    run apt-get update -o Dir::Etc::sourcelist="sources.list.d/mundix-bundle.list" \
        -o Dir::Etc::sourceparts="-" -o APT::Get::List-Cleanup="0" || true
  else
    _setup_thirdparty_repos
    run apt-get update
  fi

  log "instalando ${#APT_PACKAGES[@]} pacotes de topo (+ dependências)"
  run env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${APT_PACKAGES[@]}"
  ok "pacotes instalados"

  # Não-críticos (dados/SIEM): instalados um a um e a falha deles NÃO aborta
  # a instalação (ex.: ClickHouse >= 22.8 exige AVX — o postinst morre com
  # SIGILL em CPU sem AVX). Falhas são registradas em FAILED_NONCRIT.
  local p
  for p in "${APT_PACKAGES_NONCRIT[@]}"; do
    if run env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "$p"; then
      ok "pacote não-crítico instalado: ${p}"
    else
      warn "pacote não-crítico falhou: ${p} — a instalação continua (ajuste depois)."
      FAILED_NONCRIT+=("$p")
    fi
  done
  (( ${#FAILED_NONCRIT[@]} == 0 )) || warn "pacotes não-críticos com problema: ${FAILED_NONCRIT[*]}"
}
