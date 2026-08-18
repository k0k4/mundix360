#!/usr/bin/env bash
# Fase 70 — First-boot: dá IDENTIDADE ÚNICA ao appliance e o torna alcançável.
# Roda UMA vez (marca em /var/lib/mundix/install/firstboot). É o equivalente ao
# "assistente inicial" do pfSense: detecta NICs (adaptativo, nunca hardcode),
# define LAN de gestão, gera segredos novos e sobe os serviços.

_regen_identity() {
  step "Identidade única do appliance"
  # Chaves de host SSH novas (a imagem/bundle nunca deve carregar as do dev).
  run rm -f /etc/ssh/ssh_host_*
  run ssh-keygen -A
  # machine-id novo.
  run rm -f /etc/machine-id /var/lib/dbus/machine-id
  run systemd-machine-id-setup
  ok "chaves SSH e machine-id regenerados"
}

_detect_nics() {
  # Lista NICs físicas reais (exclui lo/virtuais), sem qualquer hardcode.
  ip -o link show 2>/dev/null | awk -F': ' '{print $2}' \
    | grep -vE '^(lo|veth|docker|br-|vnet|tun|tap|wg|virbr)' \
    | sed 's/@.*//' | sort -u
}

_bootstrap_lan() {
  step "Rede de gestão (LAN)"
  mapfile -t nics < <(_detect_nics)
  if (( ${#nics[@]} == 0 )); then
    warn "nenhuma NIC física detectada — pulei o bootstrap de LAN."
    return 0
  fi
  log "NICs detectadas: ${nics[*]}"

  local lan="${nics[0]}"
  if [[ "${ASSUME_YES:-0}" != "1" ]]; then
    echo "Selecione a interface de GESTÃO (LAN) — onde você acessará o painel:"
    select choice in "${nics[@]}"; do
      [[ -n "$choice" ]] && { lan="$choice"; break; }
    done
  fi
  ok "interface de gestão: ${lan}"

  local lan_ip="192.168.1.1" lan_cidr="192.168.1.1/24"
  # Netplan de bootstrap (a app assume a gestão depois, via netiface).
  if ! ls /etc/netplan/*mundix* >/dev/null 2>&1; then
    run bash -c "cat > /etc/netplan/90-mundix-bootstrap.yaml <<EOF
network:
  version: 2
  renderer: networkd
  ethernets:
    ${lan}:
      dhcp4: false
      addresses: [${lan_cidr}]
EOF"
    run chmod 600 /etc/netplan/90-mundix-bootstrap.yaml
    run netplan apply || warn "netplan apply falhou — verifique no console."
    ok "LAN ${lan} = ${lan_cidr}"
  fi

  # DHCP simples na LAN para o operador plugar um notebook e já receber IP.
  if [[ ! -e /etc/dnsmasq.d/00-mundix-bootstrap.conf ]]; then
    run bash -c "cat > /etc/dnsmasq.d/00-mundix-bootstrap.conf <<EOF
interface=${lan}
dhcp-range=192.168.1.50,192.168.1.150,12h
dhcp-option=3,${lan_ip}
dhcp-option=6,${lan_ip}
EOF"
    run systemctl restart dnsmasq || true
  fi

  # Publica o painel na LAN (UI hoje escuta só em 127.0.0.1).
  if [[ ! -e /etc/nginx/conf.d/mundix-mgmt.conf ]]; then
    run bash -c "cat > /etc/nginx/conf.d/mundix-mgmt.conf <<EOF
server {
    listen ${lan_ip}:443 ssl;
    listen ${lan_ip}:80;
    server_name _;
    ssl_certificate     /etc/mundix/mgmt.crt;
    ssl_certificate_key /etc/mundix/mgmt.key;
    location / { proxy_pass http://127.0.0.1:8099; proxy_set_header Host \\\$host; }
}
EOF"
    # Certificado self-signed para o painel.
    if [[ ! -e /etc/mundix/mgmt.crt ]]; then
      run openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
        -keyout /etc/mundix/mgmt.key -out /etc/mundix/mgmt.crt \
        -subj "/CN=mundix-appliance" 2>/dev/null || warn "openssl indisponível p/ cert."
    fi
    run nginx -t && run systemctl reload nginx || warn "recarregue o nginx manualmente."
  fi
  MGMT_URL="https://${lan_ip}"
}

_set_master_password() {
  step "Senha mestra"
  local pw="${MUNDIX_MASTER_PASSWORD:-}"
  if [[ -z "$pw" ]]; then
    if [[ "${ASSUME_YES:-0}" == "1" ]]; then
      pw="$(openssl rand -base64 12 2>/dev/null | tr -d '/+=' | cut -c1-14)"
      GENERATED_PW="$pw"
    else
      read -rsp "Defina a senha mestra do painel: " pw; echo
    fi
  fi
  ( cd "${MUNDIX_ROOT}/dashboard/backend" \
    && run "${MUNDIX_VENV}/bin/python" -m app.admin reset-master-password --password "$pw" ) \
    && ok "senha mestra definida" || warn "falha ao definir senha mestra (use app.admin depois)."

  # Usuário 'admin' do painel: a senha mestra NÃO cria usuário (sem isso o
  # login dá 401). Idempotente — "já existe" é sucesso; nunca falha a fase.
  local out rc=0
  out="$(cd "${MUNDIX_ROOT}/dashboard/backend" \
    && run "${MUNDIX_VENV}/bin/python" -m app.admin create-admin admin --password "$pw" 2>&1)" || rc=$?
  if (( rc == 0 )); then
    ok "usuário 'admin' do painel criado"
  elif grep -q "já existe" <<<"$out"; then
    ok "usuário 'admin' já existe — mantido (senha inalterada)"
  else
    warn "falha ao criar o usuário 'admin' (${out}) — rode depois: cd ${MUNDIX_ROOT}/dashboard/backend && ${MUNDIX_VENV}/bin/python -m app.admin create-admin admin"
  fi
}

_set_openrouter() {
  local key="${OPENROUTER_API_KEY:-}"
  [[ -z "$key" ]] && return 0
  step "IA (OpenRouter)"
  run bash -c "sed -i '/^OPENROUTER_API_KEY=/d' '${MUNDIX_ROOT}/configs/openrouter.env' 2>/dev/null; \
               echo 'OPENROUTER_API_KEY=${key}' >> '${MUNDIX_ROOT}/configs/openrouter.env'"
  ok "chave OpenRouter gravada"
}

_fix_local_dns() {
  step "Resolvedor local (dnsmasq na porta 53)"
  # O systemd-resolved segura a 53 e conflita com o dnsmasq do appliance.
  if systemctl is-active --quiet systemd-resolved 2>/dev/null; then
    run systemctl disable --now systemd-resolved >/dev/null 2>&1 || true
    ok "systemd-resolved desabilitado"
  fi
  if [[ -L /etc/resolv.conf ]]; then
    run rm -f /etc/resolv.conf
    run bash -c "printf 'nameserver 127.0.0.1\n' > /etc/resolv.conf"
    ok "/etc/resolv.conf → dnsmasq local"
  fi
}

_expire_console_password() {
  # A ISO de autoinstall cria o usuário local "mundix" com senha padrão conhecida
  # (ver installer/iso/user-data). Como o projeto é público, essa senha não pode
  # permanecer válida: exige troca no primeiro login (console ou SSH).
  if id mundix >/dev/null 2>&1; then
    run chage -d 0 mundix && ok "usuário 'mundix': troca de senha exigida no 1º login"
  fi
}

_fix_suricata_iface() {
  # Suricata (af-packet) precisa escutar numa interface que exista NESTE hardware.
  local yaml=/etc/suricata/suricata.yaml
  [[ -f "$yaml" ]] || return 0
  local cur
  cur="$(awk '/^af-packet:/{getline; if ($0 ~ /interface:/) {gsub(/.*interface:[[:space:]]*/,""); gsub(/[[:space:]].*/,""); print; exit}}' "$yaml")"
  [[ -z "$cur" ]] && return 0
  [[ -e "/sys/class/net/$cur" ]] && return 0
  mapfile -t nics < <(_detect_nics)
  (( ${#nics[@]} > 0 )) || return 0
  run sed -i "0,/^\([[:space:]]*- interface:\)[[:space:]]*${cur}/s//\1 ${nics[0]}/" "$yaml"
  ok "suricata: af-packet ${cur} → ${nics[0]}"
}

phase_firstboot() {
  if marked firstboot; then
    ok "first-boot já executado — pulando (identidade preservada)."
    return 0
  fi
  step "FIRST-BOOT — configuração inicial do appliance"

  _regen_identity
  _expire_console_password
  _fix_local_dns
  _bootstrap_lan
  _fix_suricata_iface
  _set_master_password
  _set_openrouter

  step "Subindo serviços"
  local u
  run systemctl restart nftables.service || true
  for u in "${SYSTEM_UNITS_ENABLE[@]}"; do run systemctl restart "$u" >/dev/null 2>&1 || true; done
  for u in "${MUNDIX_UNITS[@]}"; do
    [[ "$u" == *.timer ]] && run systemctl start "$u" >/dev/null 2>&1 || run systemctl restart "$u" >/dev/null 2>&1 || true
  done

  mark firstboot

  echo
  ok "================ Mundix Security 360 pronto ================"
  echo "  Painel:  ${MGMT_URL:-https://<IP-da-LAN>}"
  echo "  Usuário: admin"
  [[ -n "${GENERATED_PW:-}" ]] && echo "  Senha mestra (gerada): ${GENERATED_PW}"
  echo "  Plugue seu notebook na LAN de gestão (DHCP ativo)."
  echo "==========================================================="
}
