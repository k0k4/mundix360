#!/usr/bin/env bash
# =============================================================================
# Mundix Security 360 — INSTALADOR COMPLETO (online, comando único)
#
# Fluxo de uso (recomendado):
#   1) Instale o Ubuntu Server 24.04 no minipc (rede com internet).
#   2) Copie/clone o repositório para a máquina.
#   3) Rode:   sudo ./installer/mundix-install.sh
#
# O que ele faz, de ponta a ponta e de forma IDEMPOTENTE:
#   - instala todos os pacotes (firewall, DNS/DHCP, WAF, IDS, SIEM, Python, Node);
#   - posiciona o código em /opt/mundix360 e cria o venv + dependências;
#   - builda o frontend (SPA);
#   - semeia as configs base (nftables ADAPTATIVO, nginx+WAF, dnsmasq);
#   - PUBLICA o painel em TODAS as interfaces (0.0.0.0:80/443) — sem depender
#     de detectar a NIC certa, então o painel fica acessível em qualquer IP;
#   - libera as portas de gestão no firewall (anti-lockout: 22/80/443);
#   - habilita, SOBE e VERIFICA cada serviço, com diagnóstico se algo falhar;
#   - define a senha mestra do painel;
#   - imprime um relatório final com as portas realmente abertas e a URL.
#
# Opções:
#   --yes, -y                 não-interativo (gera senha mestra aleatória)
#   --master-password VALOR   define a senha mestra do painel
#   --openrouter-key VALOR    grava a chave da IA (OpenRouter)
#   --regen-identity          regenera chaves SSH de host + machine-id (appliance)
#   --skip-frontend           não builda o SPA (usa dist/ existente, se houver)
#   --help, -h                esta ajuda
#
# Também aceita via ambiente:
#   MUNDIX_MASTER_PASSWORD=...   OPENROUTER_API_KEY=...
# =============================================================================
set -euo pipefail

# --------------------------------------------------------------------- setup ---
INSTALLER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_ROOT="$(cd "${INSTALLER_DIR}/.." && pwd)"
LOG="/var/log/mundix-install.log"

ASSUME_YES=0
REGEN_IDENTITY=0
SKIP_FRONTEND=0
MASTER_PW="${MUNDIX_MASTER_PASSWORD:-}"
OR_KEY="${OPENROUTER_API_KEY:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y)            ASSUME_YES=1 ;;
    --master-password)   MASTER_PW="${2:-}"; shift ;;
    --openrouter-key)    OR_KEY="${2:-}"; shift ;;
    --regen-identity)    REGEN_IDENTITY=1 ;;
    --skip-frontend)     SKIP_FRONTEND=1 ;;
    -h|--help)           sed -n '2,45p' "$0"; exit 0 ;;
    *) echo "opção desconhecida: $1" >&2; exit 2 ;;
  esac
  shift
done

# Carrega o manifesto (fonte única: pacotes, units, caminhos).
# shellcheck source=manifest.env
source "${INSTALLER_DIR}/manifest.env"

# ------------------------------------------------------------------- helpers ---
if [[ -t 1 ]]; then
  C0=$'\e[0m'; CB=$'\e[34m'; CG=$'\e[32m'; CY=$'\e[33m'; CR=$'\e[31m'; CD=$'\e[2m'
else
  C0=""; CB=""; CG=""; CY=""; CR=""; CD=""
fi
log()  { printf '%s[mundix]%s %s\n' "$CB" "$C0" "$*" | tee -a "$LOG"; }
ok()   { printf '%s[ ok ]%s %s\n'  "$CG" "$C0" "$*" | tee -a "$LOG"; }
warn() { printf '%s[warn]%s %s\n'  "$CY" "$C0" "$*" | tee -a "$LOG" >&2; }
err()  { printf '%s[fail]%s %s\n'  "$CR" "$C0" "$*" | tee -a "$LOG" >&2; }
die()  { err "$*"; echo "Log completo: ${LOG}" >&2; exit 1; }
step() { printf '\n%s==>%s %s\n' "$CB" "$C0" "$*" | tee -a "$LOG"; }

FAILED_CRITICAL=()
FAILED_NONCRIT=()

confirm() {
  [[ "$ASSUME_YES" == "1" ]] && return 0
  local ans; read -rp "$1 [s/N] " ans; [[ "$ans" =~ ^[sSyY]$ ]]
}

# Sobe (ou reinicia) um serviço e VERIFICA que ficou ativo. $2=1 => crítico.
start_verify() {
  local unit="$1" critical="${2:-0}"
  systemctl enable "$unit" >>"$LOG" 2>&1 || true
  if systemctl restart "$unit" >>"$LOG" 2>&1; then
    sleep 1
    if systemctl is-active --quiet "$unit"; then ok "ativo: $unit"; return 0; fi
  fi
  warn "serviço não subiu: $unit (veja journalctl -u $unit)"
  { echo "----- journal $unit -----"; journalctl -u "$unit" --no-pager -n 25 2>&1; } >>"$LOG" || true
  if [[ "$critical" == "1" ]]; then FAILED_CRITICAL+=("$unit"); else FAILED_NONCRIT+=("$unit"); fi
  return 1
}

# ---------------------------------------------------------------- fase: preflight
phase_preflight() {
  [[ "$(id -u)" == "0" ]] || { echo "execute como root (sudo)." >&2; exit 1; }
  mkdir -p "$(dirname "$LOG")"; : >"$LOG" 2>/dev/null || true
  step "Pré-voo"
  log "log desta instalação: ${LOG}"

  local id ver
  id="$(. /etc/os-release && echo "$ID")"; ver="$(. /etc/os-release && echo "$VERSION_ID")"
  if [[ "$id" != "$TARGET_OS_ID" || "$ver" != "$TARGET_OS_VERSION" ]]; then
    warn "SO ${id} ${ver} (suportado: ${TARGET_OS_ID} ${TARGET_OS_VERSION})"
    confirm "Continuar mesmo assim?" || die "abortado pelo operador."
  else
    ok "SO ${id} ${ver}"
  fi

  log "verificando internet…"
  if curl -fsS -m 10 -o /dev/null https://deb.debian.org/ 2>/dev/null \
     || curl -fsS -m 10 -o /dev/null http://archive.ubuntu.com/ 2>/dev/null; then
    ok "internet acessível"
  else
    warn "sem confirmação de internet — o modo online precisa baixar pacotes."
    confirm "Tentar mesmo assim?" || die "sem internet; abortado."
  fi
}

# --------------------------------------------------------------- fase: código ---
phase_code() {
  step "Código do Mundix em ${MUNDIX_ROOT}"
  if [[ "$SRC_ROOT" != "$MUNDIX_ROOT" ]]; then
    log "copiando código de ${SRC_ROOT} para ${MUNDIX_ROOT}"
    install -d -m 0755 "$MUNDIX_ROOT"
    # Copia tudo, exceto artefatos pesados de build/instalação.
    rsync -a --delete \
      --exclude '/installer/bundle' \
      --exclude '/installer/dist' \
      --exclude '.git' \
      --exclude 'node_modules' \
      "${SRC_ROOT}/" "${MUNDIX_ROOT}/" 2>>"$LOG" \
      || cp -a "${SRC_ROOT}/." "${MUNDIX_ROOT}/"
  fi
  [[ -d "${MUNDIX_ROOT}/dashboard/backend/app" ]] || die "código não encontrado em ${MUNDIX_ROOT}."
  # Diretórios de estado/config.
  local d
  for d in "${MUNDIX_STATE_DIRS[@]}"; do install -d -m 0750 "$d"; done
  install -d -m 0755 /etc/nftables.d /etc/nginx/conf.d
  ok "código posicionado"
}

# ---------------------------------------------------------------- fase: apt ----
phase_apt() {
  step "Pacotes do sistema (online)"
  # Repositórios de terceiros (ClickHouse, etc.) — campos separados por '|':
  #   nome|linha-deb|url-da-chave-armored|fingerprint-keyserver(opcional)
  local entry name line key keyid keyring
  for entry in "${APT_THIRDPARTY_REPOS[@]:-}"; do
    [[ -z "$entry" ]] && continue
    IFS='|' read -r name line key keyid <<<"$entry"
    keyring="/usr/share/keyrings/mundix-${name}.gpg"
    if [[ ! -s "$keyring" ]]; then
      log "repositório de terceiros: ${name}"
      rm -f "$keyring"
      if ! curl -fsSL "$key" 2>>"$LOG" | gpg --dearmor -o "$keyring" 2>>"$LOG" || [[ ! -s "$keyring" ]]; then
        rm -f "$keyring"
        if [[ -n "${keyid:-}" ]]; then
          warn "chave de ${name} via URL indisponível; tentando keyserver…"
          gpg --no-default-keyring --keyring "$keyring" \
              --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys "$keyid" >>"$LOG" 2>&1 \
            && chmod 0644 "$keyring" \
            || warn "falha ao buscar chave de ${name} (keyserver)"
        else
          warn "falha ao buscar chave de ${name}"
        fi
      fi
    fi
    echo "deb [signed-by=${keyring}] ${line}" \
      > "/etc/apt/sources.list.d/mundix-${name}.list"
  done

  log "apt-get update…"
  DEBIAN_FRONTEND=noninteractive apt-get update >>"$LOG" 2>&1 || warn "apt-get update com avisos (veja ${LOG})"

  # Ferramentas de build necessárias APENAS no instalador online.
  local extra=(nodejs npm git rsync ca-certificates)
  log "instalando ${#APT_PACKAGES[@]} pacotes do perfil + ferramentas de build…"
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    "${APT_PACKAGES[@]}" "${extra[@]}" >>"$LOG" 2>&1 \
    || die "falha ao instalar pacotes APT (veja ${LOG})"
  ok "pacotes instalados"
}

# ------------------------------------------------------------- fase: python ----
phase_python() {
  step "Ambiente Python (venv)"
  [[ -d "$MUNDIX_VENV" ]] || python3 -m venv "$MUNDIX_VENV"
  local req="${MUNDIX_ROOT}/dashboard/backend/requirements.txt"
  [[ -f "$req" ]] || die "requirements.txt não encontrado em ${req}."
  log "instalando dependências Python…"
  "${MUNDIX_VENV}/bin/pip" install --upgrade pip >>"$LOG" 2>&1 || warn "pip upgrade falhou"
  "${MUNDIX_VENV}/bin/pip" install -r "$req" >>"$LOG" 2>&1 \
    || die "falha ao instalar dependências Python (veja ${LOG})"
  ok "dependências Python prontas"
}

# ----------------------------------------------------------- fase: frontend ----
phase_frontend() {
  step "Frontend (SPA)"
  local dist="${MUNDIX_ROOT}/dashboard/frontend/dist"
  if [[ "$SKIP_FRONTEND" == "1" ]]; then
    [[ -f "${dist}/index.html" ]] && { ok "dist existente (build pulado)"; return 0; }
    warn "--skip-frontend mas não há dist/ — buildando mesmo assim."
  fi
  command -v npm >/dev/null || die "npm ausente (esperado do apt nodejs/npm)."
  log "buildando o SPA (pode levar 1–2 min)…"
  ( cd "${MUNDIX_ROOT}/dashboard" && bash build.sh ) >>"$LOG" 2>&1 \
    || die "falha no build do frontend (veja ${LOG})"
  [[ -f "${dist}/index.html" ]] || die "build terminou mas dist/index.html não existe."
  ok "frontend buildado"
}

# ------------------------------------------------------------- fase: config ----
_seed() {  # origem destino [modo]
  local src="$1" dst="$2" mode="${3:-0644}"
  [[ -e "$dst" ]] && { log "mantido (já existe): $dst"; return 0; }
  install -D -m "$mode" "$src" "$dst"; ok "config semeada: $dst"
}

phase_config() {
  step "Configuração base"
  local cfg="${INSTALLER_DIR}/config"

  # nginx WAF reverse proxy (loopback 127.0.0.1:8099).
  _seed "${cfg}/nginx-mundix360.conf" /etc/nginx/sites-available/mundix360
  ln -sf /etc/nginx/sites-available/mundix360 /etc/nginx/sites-enabled/mundix360
  [[ -e /etc/nginx/sites-enabled/default ]] && rm -f /etc/nginx/sites-enabled/default
  install -d -m 0755 /etc/nginx/modsec
  _seed "${cfg}/modsec-main.conf" /etc/nginx/modsec/main.conf
  # Overrides referenciados pelo main.conf (engine ON + pontos de tuning do CRS).
  _seed "${cfg}/modsec-overrides.conf"  /etc/nginx/modsec/mundix-overrides.conf
  _seed "${cfg}/modsec-before-crs.conf" /etc/nginx/modsec/mundix-before-crs.conf
  _seed "${cfg}/modsec-after-crs.conf"  /etc/nginx/modsec/mundix-after-crs.conf

  # nftables base ADAPTATIVO (sem NIC hardcoded; libera 22/80/443).
  _seed "${cfg}/nftables-base.conf" /etc/nftables.conf 0755
  install -d -m 0755 /etc/nftables.d

  # dnsmasq base (DNS/DHCP + filtro de conteúdo é escrito em runtime pela app).
  if [[ -d "${cfg}/dnsmasq-base" ]]; then
    install -d -m 0755 /etc/dnsmasq.d
    install -d -m 0755 /var/log/dnsmasq   # log-facility referenciado em 00-global.conf
    local f
    for f in "${cfg}/dnsmasq-base"/*; do
      [[ -e "$f" ]] && _seed "$f" "/etc/dnsmasq.d/$(basename "$f")"
    done
  fi

  # Seeds do manifesto (ex.: openrouter.env a partir do exemplo).
  local pair src dst
  for pair in "${MUNDIX_CONFIG_SEED[@]:-}"; do
    [[ -z "$pair" ]] && continue
    src="${MUNDIX_ROOT}/${pair%%::*}"; dst="${pair##*::}"
    [[ -e "$src" ]] && _seed "$src" "$dst" 0640
  done

  # Encaminhamento de pacotes (firewall roteia entre zonas).
  echo 'net.ipv4.ip_forward=1' > /etc/sysctl.d/99-mundix-forward.conf
  sysctl --system >>"$LOG" 2>&1 || true
  ok "configuração base aplicada"
}

# ------------------------------------------------- fase: exposição do painel ----
phase_mgmt() {
  step "Exposição do painel (todas as interfaces)"
  # Certificado self-signed para HTTPS do painel.
  install -d -m 0750 /etc/mundix
  if [[ ! -e /etc/mundix/mgmt.crt ]]; then
    openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
      -keyout /etc/mundix/mgmt.key -out /etc/mundix/mgmt.crt \
      -subj "/CN=$(hostname -s 2>/dev/null || echo mundix)" >>"$LOG" 2>&1 \
      || warn "openssl falhou ao gerar o certificado."
  fi
  # Publica em 0.0.0.0:80/443 (proxy para o WAF em 127.0.0.1:8099). Assim o
  # painel é alcançável em QUALQUER IP da caixa, sem depender de detectar a NIC.
  cat > /etc/nginx/conf.d/mundix-mgmt.conf <<'NGINX'
# Mundix Security 360 — listener de gestão (todas as interfaces).
# Proxy para o reverse-proxy WAF interno (127.0.0.1:8099).
server {
    listen 0.0.0.0:80 default_server;
    listen [::]:80 default_server;
    server_name _;
    # Redireciona HTTP -> HTTPS, mas mantém o painel utilizável em HTTP também.
    location / {
        proxy_pass http://127.0.0.1:8099;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto http;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
}
server {
    listen 0.0.0.0:443 ssl default_server;
    listen [::]:443 ssl default_server;
    server_name _;
    ssl_certificate     /etc/mundix/mgmt.crt;
    ssl_certificate_key /etc/mundix/mgmt.key;
    location / {
        proxy_pass http://127.0.0.1:8099;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_read_timeout 3600s;
    }
}
NGINX
  if nginx -t >>"$LOG" 2>&1; then
    ok "listener de gestão configurado (80/443 em todas as interfaces)"
  else
    warn "nginx -t falhou — veja ${LOG}. Removendo listener para não derrubar o nginx."
    rm -f /etc/nginx/conf.d/mundix-mgmt.conf
  fi
}

# ----------------------------------------------------------- fase: units -------
phase_units() {
  step "Units do systemd"
  local u
  for u in "${MUNDIX_UNITS[@]}"; do
    install -m 0644 "${INSTALLER_DIR}/units/${u}" "/etc/systemd/system/${u}"
    log "unit instalada: ${u}"
  done
  # Remove drop-ins legados (portas/serviços antigos).
  [[ -d /etc/systemd/system/mundix-dashboard-api.service.d ]] \
    && rm -rf /etc/systemd/system/mundix-dashboard-api.service.d
  systemctl daemon-reload
  ok "units aplicadas"
}

# -------------------------------------------------- fase: subir + verificar ----
_waf_selftest() {
  # O ModSecurity do Ubuntu 24.04 (noble) tem um bug de ABI (transição t64):
  # libnginx-mod-http-modsecurity 1.0.3 + libmodsecurity3t64 3.0.12 fazem o
  # worker do nginx estourar (malloc gigante → SIGSEGV) em QUALQUER request.
  # Se o WAF estiver instável aqui, desligamos (fail-open) para não derrubar o
  # painel — o firewall/IDS continuam protegendo a gestão.
  local site=/etc/nginx/sites-available/mundix360
  grep -q '^[[:space:]]*modsecurity on;' "$site" 2>/dev/null || return 0
  local code
  code=$(curl -s -o /dev/null -m 5 -w '%{http_code}' http://127.0.0.1:8099/ 2>/dev/null || echo 000)
  case "$code" in
    2*|3*|4*) ok "WAF (ModSecurity) operacional"; return 0 ;;
  esac
  warn "WAF (ModSecurity) instável neste sistema (bug t64 do pacote do Ubuntu, HTTP=${code}) — desativando para não derrubar o painel."
  sed -i 's/^\([[:space:]]*\)modsecurity on;.*/\1modsecurity off;  # auto: ModSecurity t64 crash (Ubuntu 24.04)/' "$site"
  if nginx -t >>"$LOG" 2>&1 && systemctl reload nginx >>"$LOG" 2>&1; then
    warn "WAF desativado. Reabilite (modsecurity on) após corrigir o pacote ModSecurity."
  else
    err "falha ao desativar o WAF automaticamente; veja ${LOG}"
  fi
}

phase_services() {
  step "Subindo e verificando serviços"

  # Datastores primeiro (best-effort — a API tem Wants, não Requires).
  start_verify clickhouse-server.service 0 || true
  start_verify valkey-server.service 0 || true

  # Núcleo de rede (críticos para gestão).
  start_verify nftables.service 0 || true   # base é tolerante; não-crítico ao painel
  start_verify dnsmasq.service 0 || true
  start_verify suricata.service 0 || true

  # API + WAF (CRÍTICOS — sem eles não há painel).
  start_verify mundix-dashboard-api.service 1 || true

  # Aguarda a API responder no upstream antes de declarar o nginx pronto.
  log "aguardando a API responder em 127.0.0.1:8100…"
  local i ok_api=0
  for _ in $(seq 1 30); do
    if curl -fsS -m 3 -o /dev/null "http://127.0.0.1:8100/health" 2>/dev/null \
       || curl -fsS -m 3 -o /dev/null "http://127.0.0.1:8100/" 2>/dev/null; then
      ok_api=1; break
    fi
    sleep 1
  done
  [[ "$ok_api" == "1" ]] && ok "API respondendo" || warn "API não respondeu em 30s (veja ${LOG})"

  start_verify nginx.service 1 || true
  _waf_selftest

  # Serviços auxiliares do Mundix.
  for u in "${MUNDIX_UNITS[@]}"; do
    [[ "$u" == "mundix-dashboard-api.service" ]] && continue
    if [[ "$u" == *.timer ]]; then
      systemctl enable --now "$u" >>"$LOG" 2>&1 && ok "ativo: $u" || warn "timer não subiu: $u"
    else
      start_verify "$u" 0 || true
    fi
  done

  # Desabilita componentes fora do perfil núcleo (caso de imagem clonada).
  for u in "${PROFILE_DISABLE_UNITS[@]:-}"; do
    [[ -z "$u" ]] && continue
    if systemctl is-enabled "$u" >/dev/null 2>&1; then
      systemctl disable --now "$u" >>"$LOG" 2>&1 || true
    fi
  done
}

# ------------------------------------------------ fase: identidade (appliance) --
phase_identity() {
  [[ "$REGEN_IDENTITY" == "1" ]] || return 0
  step "Identidade única (regenerando)"
  rm -f /etc/ssh/ssh_host_* && ssh-keygen -A >>"$LOG" 2>&1 || true
  rm -f /etc/machine-id /var/lib/dbus/machine-id && systemd-machine-id-setup >>"$LOG" 2>&1 || true
  ok "chaves SSH de host + machine-id regenerados"
}

# ----------------------------------------------------- fase: senha + ia --------
phase_secrets() {
  step "Senha mestra do painel"
  local pw="$MASTER_PW"
  if [[ -z "$pw" ]]; then
    if [[ "$ASSUME_YES" == "1" ]]; then
      pw="$(openssl rand -base64 12 | tr -d '/+=' | cut -c1-14)"; GENERATED_PW="$pw"
    else
      local p2
      while :; do
        read -rsp "Defina a senha mestra do painel: " pw; echo
        read -rsp "Confirme a senha: " p2; echo
        [[ "$pw" == "$p2" && -n "$pw" ]] && break
        warn "senhas não conferem (ou vazia) — tente de novo."
      done
    fi
  fi
  if ( cd "${MUNDIX_ROOT}/dashboard/backend" \
       && "${MUNDIX_VENV}/bin/python" -m app.admin reset-master-password --password "$pw" ) >>"$LOG" 2>&1; then
    ok "senha mestra definida"
  else
    warn "falha ao definir senha mestra — use: cd ${MUNDIX_ROOT}/dashboard/backend && ${MUNDIX_VENV}/bin/python -m app.admin reset-master-password"
  fi

  if [[ -n "$OR_KEY" ]]; then
    step "IA (OpenRouter)"
    local envf="${MUNDIX_ROOT}/configs/openrouter.env"
    install -d -m 0750 "$(dirname "$envf")"
    sed -i '/^OPENROUTER_API_KEY=/d' "$envf" 2>/dev/null || true
    echo "OPENROUTER_API_KEY=${OR_KEY}" >> "$envf"
    chmod 0640 "$envf"
    ok "chave OpenRouter gravada"
  fi
}

# ----------------------------------------------------------- fase: relatório ---
phase_report() {
  step "Relatório final"
  echo | tee -a "$LOG"
  # IPs utilizáveis da caixa (exclui loopback).
  local ips
  ips="$(ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | paste -sd' ' -)"
  [[ -z "$ips" ]] && ips="(nenhum IP global — configure a rede)"

  echo "Portas em escuta (relevantes):" | tee -a "$LOG"
  ss -tlnp 2>/dev/null | awk 'NR==1 || /:(80|443|53|8100|8099)\>/' | tee -a "$LOG" || true
  echo | tee -a "$LOG"

  # Teste real do painel via o listener de gestão.
  local panel_ok=0
  if curl -k -fsS -m 5 -o /dev/null https://127.0.0.1/ 2>/dev/null; then panel_ok=1; fi

  ok "============== Mundix Security 360 ==============="
  echo "  Painel:  https://<IP>  (HTTP também em http://<IP>)" | tee -a "$LOG"
  echo "  IPs desta caixa: ${ips}" | tee -a "$LOG"
  echo "  Usuário: admin" | tee -a "$LOG"
  [[ -n "${GENERATED_PW:-}" ]] && echo "  Senha mestra (gerada): ${GENERATED_PW}" | tee -a "$LOG"
  [[ "$panel_ok" == "1" ]] && echo "  Status do painel: RESPONDENDO ✔" | tee -a "$LOG" \
                           || echo "  Status do painel: sem resposta local (veja ${LOG})" | tee -a "$LOG"
  echo "  Log: ${LOG}" | tee -a "$LOG"
  echo "=================================================" | tee -a "$LOG"

  if (( ${#FAILED_CRITICAL[@]} > 0 )); then
    err "Serviços CRÍTICOS que não subiram: ${FAILED_CRITICAL[*]}"
    err "Investigue com: journalctl -u <serviço> --no-pager -n 50"
    return 1
  fi
  if (( ${#FAILED_NONCRIT[@]} > 0 )); then
    warn "Serviços não-críticos com problema: ${FAILED_NONCRIT[*]} (painel funciona; ajuste depois)"
  fi
  return 0
}

# --------------------------------------------------------------------- main ----
printf '%s\n' "
  __  __                 _ _      _____  __  ___
 |  \/  |_   _ _ __   __| (_)_  _|___ / / /_ / _ \\
 | |\/| | | | | '_ \ / _\` | \ \/ / |_ \| '_ \ | | |
 | |  | | |_| | | | | (_| | |>  < ___) | (_) | |_| |
 |_|  |_|\__,_|_| |_|\__,_|_/_/\_\____/ \___/ \___/
        Security 360 — Instalador completo (${MUNDIX_VERSION}, perfil ${MUNDIX_PROFILE})
"

phase_preflight
phase_code
phase_apt
phase_python
phase_frontend
phase_config
phase_mgmt
phase_units
phase_services
phase_identity
phase_secrets
phase_report
