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
    local repo="${BUNDLE_DIR}/debs"
    run bash -c "cd '${repo}' && dpkg-scanpackages -m . > Packages 2>/dev/null"
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
}
