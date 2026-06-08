#!/usr/bin/env bash
# Fase 10 — Pacotes APT (offline a partir do bundle, ou online via repositórios).

_setup_thirdparty_repos() {
  # Apenas no modo online: registra repositórios de terceiros (ex.: ClickHouse).
  # Campos separados por '|' (URLs contêm ':'):
  #   nome|linha-deb|url-da-chave-armored|fingerprint-keyserver(opcional)
  local entry name line key keyid keyring
  for entry in "${APT_THIRDPARTY_REPOS[@]}"; do
    IFS='|' read -r name line key keyid <<<"$entry"
    keyring="/usr/share/keyrings/mundix-${name}.gpg"
    if [[ ! -s "$keyring" ]]; then
      log "registrando repositório ${name}"
      run rm -f "$keyring"
      if ! run bash -c "curl -fsSL '${key}' | gpg --dearmor -o '${keyring}'" || [[ ! -s "$keyring" ]]; then
        run rm -f "$keyring"
        if [[ -n "${keyid:-}" ]]; then
          warn "chave de ${name} via URL indisponível; tentando keyserver…"
          run gpg --no-default-keyring --keyring "$keyring" \
              --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys "$keyid" \
            && run chmod 0644 "$keyring" \
            || warn "falha ao buscar chave de ${name} (keyserver)"
        else
          warn "falha ao buscar chave de ${name}"
        fi
      fi
    fi
    run bash -c "echo 'deb [signed-by=${keyring}] ${line}' > /etc/apt/sources.list.d/mundix-${name}.list"
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
