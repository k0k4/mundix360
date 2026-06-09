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
  fi

  # ClickHouse: perfil de baixo consumo (desativa logs de auto-instrumentação
  # de alto churn — crítico no Atom de 2 núcleos). O dir config.d pertence ao
  # usuário clickhouse, então ajustamos o dono após semear.
  if [[ -f "${cfg}/clickhouse/mundix-lowpower.xml" && -d /etc/clickhouse-server/config.d ]]; then
    if [[ ! -e /etc/clickhouse-server/config.d/mundix-lowpower.xml ]]; then
      _seed_file "${cfg}/clickhouse/mundix-lowpower.xml" \
        /etc/clickhouse-server/config.d/mundix-lowpower.xml 0640
      run chown clickhouse:clickhouse /etc/clickhouse-server/config.d/mundix-lowpower.xml
    fi
  fi

  # Seeds declarados no manifesto (ex.: openrouter.env a partir do exemplo).
  local pair src dst
  for pair in "${MUNDIX_CONFIG_SEED[@]}"; do
    src="${MUNDIX_ROOT}/${pair%%::*}"; dst="${pair##*::}"
    [[ -e "$src" ]] && _seed_file "$src" "$dst" 0640
  done

  ok "configuração base aplicada"
}
