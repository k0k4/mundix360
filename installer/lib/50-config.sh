#!/usr/bin/env bash
# Fase 50 — Semeia configs canônicas (nginx WAF, ModSecurity, nftables base,
# dnsmasq). NUNCA sobrescreve config já existente do operador (idempotente).

_seed_file() {  # origem destino [modo]
  local src="$1" dst="$2" mode="${3:-0644}"
  if [[ -e "$dst" ]]; then
    log "mantido (já existe): $dst"
    return 0
  fi
  run install -D -m "$mode" "$src" "$dst"
  ok "config semeada: $dst"
}

# O mundix-lowpower.xml usa chaves de logs introduzidas depois do 22.3
# (backup_log, filesystem_cache_log, asynchronous_insert_log,
# processors_profile_log...). Como CPUs sem AVX são pinadas no 22.3 (ver
# lib/00-preflight.sh), o seed só é seguro com ClickHouse >= 23 instalado.
_clickhouse_ge_23() {
  local ver major
  ver="$(dpkg-query -W -f='${Version}' clickhouse-server 2>/dev/null)" || return 1
  major="${ver%%.*}"
  [[ "$major" =~ ^[0-9]+$ ]] || return 1
  (( major >= 23 ))
}

phase_config() {
  step "Configuração base"
  local cfg="${INSTALLER_DIR}/config"

  # nginx WAF reverse proxy.
  _seed_file "${cfg}/nginx-mundix360.conf" /etc/nginx/sites-available/mundix360
  if [[ ! -e /etc/nginx/sites-enabled/mundix360 ]]; then
    run ln -sf /etc/nginx/sites-available/mundix360 /etc/nginx/sites-enabled/mundix360
  fi
  # Remove o site default do nginx para não conflitar.
  [[ -e /etc/nginx/sites-enabled/default ]] && run rm -f /etc/nginx/sites-enabled/default

  # ModSecurity.
  _seed_file "${cfg}/modsec-main.conf" /etc/nginx/modsec/main.conf
  _seed_file "${cfg}/modsec-overrides.conf" /etc/nginx/modsec/mundix-overrides.conf
  _seed_file "${cfg}/modsec-before-crs.conf" /etc/nginx/modsec/mundix-before-crs.conf
  _seed_file "${cfg}/modsec-after-crs.conf" /etc/nginx/modsec/mundix-after-crs.conf

  # nftables base (inclui os arquivos gerenciados em runtime pelo fwmanage).
  _seed_file "${cfg}/nftables-base.conf" /etc/nftables.conf
  run install -d -m 0755 /etc/nftables.d

  # dnsmasq base (DNS/DHCP + filtro de conteúdo é escrito em runtime pela app).
  if [[ -d "${cfg}/dnsmasq-base" ]]; then
    run install -d -m 0755 /etc/dnsmasq.d
    local f
    for f in "${cfg}/dnsmasq-base"/*; do
      [[ -e "$f" ]] || continue
      _seed_file "$f" "/etc/dnsmasq.d/$(basename "$f")"
    done
    # O 00-global.conf loga em /var/log/dnsmasq/ — sem o diretório o serviço
    # não sobe (o dnsmasq não cria o path sozinho ao abrir o log).
    run install -d -o dnsmasq -g nogroup -m 0755 /var/log/dnsmasq
    # Upstreams de DNS: o 00-global.conf tem `no-resolv` — sem `server=` o
    # appliance fica sem resolver nada depois que o first-boot desliga o
    # systemd-resolved. Semeia defaults públicos, sem sobrescrever o operador.
    if [[ ! -e /etc/dnsmasq.d/mundix-dns-resolvers.conf ]]; then
      run bash -c "printf 'server=1.1.1.1\nserver=9.9.9.9\n' > /etc/dnsmasq.d/mundix-dns-resolvers.conf"
      ok "upstreams DNS semeados: /etc/dnsmasq.d/mundix-dns-resolvers.conf"
    fi
  fi

  # ClickHouse: perfil de baixo consumo (desativa logs de auto-instrumentação
  # de alto churn — crítico no Atom de 2 núcleos). O dir config.d pertence ao
  # usuário clickhouse, então ajustamos o dono após semear. Só semeia com
  # ClickHouse >= 23: no 22.3 (pin de CPU sem AVX) várias chaves são
  # desconhecidas e o seed não é seguro.
  if [[ -f "${cfg}/clickhouse/mundix-lowpower.xml" && -d /etc/clickhouse-server/config.d ]]; then
    if [[ ! -e /etc/clickhouse-server/config.d/mundix-lowpower.xml ]]; then
      if _clickhouse_ge_23; then
        _seed_file "${cfg}/clickhouse/mundix-lowpower.xml" \
          /etc/clickhouse-server/config.d/mundix-lowpower.xml 0640
        # "|| warn": se o ClickHouse ficou meio-instalado (postinst falhou), o
        # usuário pode não existir — e isso não pode abortar o instalador.
        run chown clickhouse:clickhouse /etc/clickhouse-server/config.d/mundix-lowpower.xml \
          || warn "chown do lowpower.xml falhou (usuário clickhouse ausente?)"
      else
        log "ClickHouse < 23 (ou versão indetectável): mundix-lowpower.xml NÃO semeado."
      fi
    fi
  fi

  # Seeds declarados no manifesto (ex.: openrouter.env a partir do exemplo).
  local pair src dst
  for pair in "${MUNDIX_CONFIG_SEED[@]}"; do
    src="${MUNDIX_ROOT}/${pair%%::*}"; dst="${pair##*::}"
    [[ -e "$src" ]] && _seed_file "$src" "$dst" 0640
  done

  # Menu de console de recuperação (estilo pfSense): comando global + abertura
  # automática no login root do console local (SSH nunca é interceptado).
  if [[ -f "${MUNDIX_ROOT}/scripts/setup/mundix-menu.sh" ]]; then
    run ln -sf "${MUNDIX_ROOT}/scripts/setup/mundix-menu.sh" /usr/local/bin/mundix-menu
    run chmod 0755 "${MUNDIX_ROOT}/scripts/setup/mundix-menu.sh"
    run install -D -m 0644 "${MUNDIX_ROOT}/scripts/setup/mundix-menu.profile" /etc/profile.d/mundix-menu.sh
    ok "menu de console instalado (/usr/local/bin/mundix-menu)"
  fi

  # Export HTTP temporário dos artefatos (ISO/bundle) para download.
  if [[ -f "${MUNDIX_ROOT}/scripts/setup/mundix-export.sh" ]]; then
    run ln -sf "${MUNDIX_ROOT}/scripts/setup/mundix-export.sh" /usr/local/bin/mundix-export
    run chmod 0755 "${MUNDIX_ROOT}/scripts/setup/mundix-export.sh"
    ok "export instalado (/usr/local/bin/mundix-export)"
  fi

  # Canal de atualizações estáveis (repo APT assinado, só o pacote mundix360).
  # A sources.list é REGRAVADA se divergir (idempotente); sem a chave no repo,
  # apenas avisa — a ausência do canal não pode abortar a instalação.
  local repo_key="${cfg}/mundix-repo.gpg"
  if [[ -f "$repo_key" ]]; then
    run install -m 0644 "$repo_key" /usr/share/keyrings/mundix-repo.gpg
    local upd_line="deb [signed-by=/usr/share/keyrings/mundix-repo.gpg] https://k0k4.github.io/mundix360-repo stable main"
    local upd_list=/etc/apt/sources.list.d/mundix360.list
    if [[ "$(cat "$upd_list" 2>/dev/null || true)" != "$upd_line" ]]; then
      run bash -c "printf '%s\n' '${upd_line}' > '${upd_list}'"
      ok "canal de atualizações configurado: ${upd_list}"
    fi
  else
    warn "chave do canal de updates ausente (${repo_key}) — canal não semeado"
  fi

  ok "configuração base aplicada"
}
