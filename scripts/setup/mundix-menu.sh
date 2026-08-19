#!/usr/bin/env bash
# =============================================================================
# Mundix Security 360 — Menu de console (setup/recuperação, estilo pfSense)
#
# Pensado para o console LOCAL do appliance quando a web não está acessível:
# ver status, consertar rede/firewall, recuperar o acesso ao painel, restaurar
# backup.
# Zero dependências além do sistema base (bash, iproute2, systemd, jq opcional).
#
# Abre automaticamente no login root do console local (via /etc/profile.d/) ou
# manualmente com:  mundix-menu
# =============================================================================

# Sem `set -e` de propósito: um comando que falha não pode derrubar o menu.
set -o pipefail

MUNDIX_ROOT="/opt/mundix360"
MANIFEST="${MUNDIX_ROOT}/installer/manifest.env"
NETPLAN_BOOT="/etc/netplan/90-mundix-bootstrap.yaml"
VERSION="?"
[[ -r "$MANIFEST" ]] && VERSION="$(grep -m1 '^MUNDIX_VERSION=' "$MANIFEST" | cut -d'"' -f2)"

# Cores (só se o terminal suportar).
if [[ -t 1 ]]; then
  C_RED=$'\033[0;31m'; C_GRN=$'\033[0;32m'; C_YEL=$'\033[1;33m'
  C_BLU=$'\033[0;34m'; C_BOLD=$'\033[1m'; C_NC=$'\033[0m'
fi
ok()   { echo "${C_GRN}[ OK ]${C_NC} $*"; }
warn() { echo "${C_YEL}[AVISO]${C_NC} $*"; }
err()  { echo "${C_RED}[ERRO]${C_NC} $*"; }
pause() { echo; read -rp "Pressione Enter para voltar ao menu... " _; }

# NICs físicas reais (mesma lógica do first-boot do instalador).
detect_nics() {
  ip -o link show 2>/dev/null | awk -F': ' '{print $2}' \
    | grep -vE '^(lo|veth|docker|br-|vnet|tun|tap|wg|virbr|ppp)' \
    | sed 's/@.*//' | sort -u
}

require_root() {
  if [[ $EUID -ne 0 ]]; then
    err "Este menu precisa de root (rode: sudo mundix-menu)."
    exit 1
  fi
}

# ------------------------------------------------------------------- ações ---

act_status() {
  echo "=== Status geral ==="
  if [[ -x "${MUNDIX_ROOT}/scripts/ops/mundix360-healthcheck.sh" ]]; then
    "${MUNDIX_ROOT}/scripts/ops/mundix360-healthcheck.sh" || warn "healthcheck retornou erros (veja acima)."
  else
    warn "healthcheck não encontrado — resumo simples:"
  fi
  echo
  echo "--- Units Mundix ---"
  systemctl list-units 'mundix*' 'openvpn*' dnsmasq nftables nginx clickhouse-server suricata \
    --no-pager --no-legend 2>/dev/null | awk '{printf "%-45s %s\n", $1, $4}' || true
  pause
}

act_interfaces() {
  echo "=== Interfaces de rede ==="
  echo
  echo "--- Links (estado) ---";      ip -br link 2>/dev/null || true
  echo; echo "--- Endereços IPv4 ---";  ip -br -4 addr 2>/dev/null || true
  echo; echo "--- Rotas default ---";   ip route show default 2>/dev/null || echo "(nenhuma)"
  echo
  for f in /etc/mundix/interfaces.json /etc/mundix/pppoe.json /etc/mundix/multiwan.json; do
    if [[ -r "$f" ]]; then
      echo "--- $f ---"
      if command -v jq >/dev/null 2>&1; then jq . "$f" 2>/dev/null || cat "$f"; else cat "$f"; fi
      echo
    fi
  done
  pause
}

act_config_lan() {
  echo "=== Configurar LAN de gestão ==="
  mapfile -t nics < <(detect_nics)
  if ((${#nics[@]} == 0)); then err "nenhuma NIC física detectada."; pause; return; fi

  echo "NICs detectadas:"
  local i
  for i in "${!nics[@]}"; do printf "  %d) %s\n" "$((i+1))" "${nics[$i]}"; done
  read -rp "Interface de gestão [${nics[0]}]: " pick
  local lan="${nics[0]}"
  [[ -n "$pick" ]] && [[ "$pick" =~ ^[0-9]+$ ]] && (( pick >= 1 && pick <= ${#nics[@]} )) \
    && lan="${nics[$((pick-1))]}"

  local cur_ip="192.168.1.1/24"
  [[ -r "$NETPLAN_BOOT" ]] && cur_ip="$(grep -oP 'addresses:\s*\[\K[^]]+' "$NETPLAN_BOOT" | head -1)"
  cur_ip="${cur_ip:-192.168.1.1/24}"
  read -rp "IP/máscara da LAN [$cur_ip]: " new_ip
  new_ip="${new_ip:-$cur_ip}"
  if [[ ! "$new_ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/[0-9]+$ ]]; then
    err "formato inválido (use A.B.C.D/NN). Nada alterado."; pause; return
  fi

  if [[ -f "$NETPLAN_BOOT" ]]; then
    cp -a "$NETPLAN_BOOT" "${NETPLAN_BOOT}.bak-$(date +%Y%m%d-%H%M%S)"
    ok "backup do netplan anterior criado"
  fi
  cat > "$NETPLAN_BOOT" <<EOF
network:
  version: 2
  renderer: networkd
  ethernets:
    ${lan}:
      dhcp4: false
      addresses: [${new_ip}]
EOF
  chmod 600 "$NETPLAN_BOOT"
  ok "LAN gravada em $NETPLAN_BOOT (${lan} = ${new_ip})"

  # DHCP estilo pfSense: mesma rota do painel (app.services.network.save_zone).
  echo
  local dhcp_resumo="desativado"
  read -rp "Ativar servidor DHCP nesta interface? [s/N] " want_dhcp
  if [[ "$want_dhcp" =~ ^[sS]$ ]]; then
    lan_dhcp_via_painel "$lan" "$new_ip" && dhcp_resumo="$LAN_DHCP_RESUMO" \
      || dhcp_resumo="${LAN_DHCP_RESUMO:-FALHOU (veja acima)}"
  fi

  echo
  echo "--- Resumo ---"
  echo "  Interface : ${lan}"
  echo "  IP/máscara: ${new_ip}"
  echo "  DHCP      : ${dhcp_resumo}"
  warn "NÃO foi aplicado ainda — use a opção 4 (Aplicar rede) quando estiver pronto."
  pause
}

# ------------------------------------------------ LAN DHCP (via código do painel) ---

# Grava/atualiza a zona 'lan' do dnsmasq chamando o MESMO código do painel
# (app.services.network.save_zone): escreve /etc/dnsmasq.d/lan.conf, valida com
# `dnsmasq --test`, reinicia o dnsmasq e re-renderiza o firewall (portas 53/67).
# NOTA: roda num processo separado do da API — aceitável num console de
# recuperação, onde não há concorrência real com o painel.
# Args: <nic> <ip/máscara CIDR> <auto|update>. Saída: "POOL:<ini>-<fim>",
# "CONFLITO:<iface>" (rc=3) ou nada em caso de erro (rc!=0).
_lan_zone_save() {
  (cd "${MUNDIX_ROOT}/dashboard/backend" && /opt/venv/bin/python - "$1" "$2" "$3" <<'PY'
import ipaddress
import sys

from app.services import network

nic, cidr, mode = sys.argv[1], sys.argv[2], sys.argv[3]
addr = ipaddress.ip_interface(cidr)
ip, mask, net = str(addr.ip), str(addr.network.netmask), addr.network

existing = network.get_zone("lan")
create = True
if existing and existing.get("config_present"):
    cur = existing.get("interface")
    if cur and cur != nic and mode != "update":
        print(f"CONFLITO:{cur}")
        sys.exit(3)
    create = False

z = {"zone": "lan", "interface": nic, "listen_address": ip, "netmask": mask}
# Pool: preserva o existente se a sub-rede não mudou; senão deriva pela regra
# do painel (rede+10 .. broadcast-5; gateway = IP do appliance).
if (not create and existing.get("dhcp_start") and existing.get("network")
        and existing["network"] == str(net)):
    z["dhcp_start"] = existing["dhcp_start"]
    z["dhcp_end"] = existing["dhcp_end"]
    if existing.get("gateway"):
        z["gateway"] = existing["gateway"]
else:
    network._lan_dhcp_default(z)

saved = network.save_zone(z, create=create)
if saved.get("dhcp_start") and saved.get("dhcp_end"):
    print(f"POOL:{saved['dhcp_start']}-{saved['dhcp_end']}")
else:
    print("POOL:")
PY
  )
}

# Pergunta/resolve conflitos e chama _lan_zone_save. Preenche LAN_DHCP_RESUMO.
lan_dhcp_via_painel() {
  local lan="$1" cidr="$2"
  LAN_DHCP_RESUMO=""
  if [[ ! -x /opt/venv/bin/python ]]; then
    err "venv não encontrado em /opt/venv — ative o DHCP depois pelo painel."
    LAN_DHCP_RESUMO="PENDENTE (sem venv — configure pelo painel)"
    return 1
  fi
  local out rc=0
  out="$(_lan_zone_save "$lan" "$cidr" auto)" || rc=$?
  if (( rc == 3 )); then
    local other="${out#CONFLITO:}"
    warn "a zona 'lan' já existe na interface ${other}."
    read -rp "Atualizar a zona 'lan' para ${lan}? [s/N] " c
    if [[ ! "$c" =~ ^[sS]$ ]]; then
      echo "DHCP não alterado."
      LAN_DHCP_RESUMO="mantido na interface ${other}"
      return 1
    fi
    rc=0
    out="$(_lan_zone_save "$lan" "$cidr" update)" || rc=$?
  fi
  if (( rc != 0 )); then
    err "falha ao salvar a zona 'lan' (veja acima)."
    LAN_DHCP_RESUMO="FALHOU (veja acima)"
    return 1
  fi
  local pool="${out#POOL:}"
  if [[ -n "$pool" ]]; then
    ok "zona 'lan' gravada — DHCP ativo em ${lan} (pool ${pool})"
    LAN_DHCP_RESUMO="ativo em ${lan} (pool ${pool})"
  else
    ok "zona 'lan' gravada em ${lan} (sub-rede pequena demais para pool DHCP)"
    LAN_DHCP_RESUMO="zona gravada em ${lan}, sem pool derivável"
  fi
}

act_apply_network() {
  echo "=== Aplicar rede e firewall ==="
  echo "1) netplan try (reverte sozinho em 30s se você não confirmar — SEGURO)"
  echo "2) netplan apply (definitivo — pode derrubar sua sessão!)"
  echo "3) Só validar/recarregar o firewall (nftables)"
  echo "0) Voltar"
  read -rp "Escolha: " sub
  case "$sub" in
    1) netplan try --timeout=30 || warn "netplan try abortado/revertido." ;;
    2) read -rp "Tem certeza? A sessão pode cair. [s/N] " c
       [[ "$c" =~ ^[sS]$ ]] && { netplan apply && ok "netplan aplicado."; } || echo "cancelado." ;;
    3) : ;;
    *) return ;;
  esac
  if [[ -f /etc/nftables.conf ]]; then
    if nft -c -f /etc/nftables.conf 2>/dev/null; then
      systemctl restart nftables && ok "nftables válido e recarregado."
    else
      err "/etc/nftables.conf INVÁLIDO — nftables NÃO foi recarregado."
    fi
  fi
  pause
}

act_recover_access() {
  echo "=== Recuperar acesso ao painel ==="
  echo "1) Senha do admin do painel (login web) — redefine, reativa a conta e revoga sessões"
  echo "2) Senha mestra da IA (assistente de IA — NÃO é a senha de login)"
  echo "0) Voltar"
  read -rp "Escolha: " sub
  case "$sub" in
    1)
      if [[ -x "${MUNDIX_ROOT}/scripts/reset-admin-password.sh" ]]; then
        "${MUNDIX_ROOT}/scripts/reset-admin-password.sh" || warn "recuperação não concluída (veja acima)."
      else
        err "scripts/reset-admin-password.sh não encontrado."
      fi ;;
    2)
      if [[ -x "${MUNDIX_ROOT}/scripts/reset-master-password.sh" ]]; then
        "${MUNDIX_ROOT}/scripts/reset-master-password.sh" || err "falha no reset (veja acima)."
      else
        err "scripts/reset-master-password.sh não encontrado."
      fi ;;
    *) ;;
  esac
  pause
}

act_restart_services() {
  echo "=== Reiniciar serviços ==="
  local svcs=(nftables dnsmasq nginx suricata clickhouse-server
              mundix-dashboard-api mundix-siem-ingest mundix-active-response)
  local s
  for s in "${svcs[@]}"; do
    if systemctl cat "$s" >/dev/null 2>&1; then
      if systemctl restart "$s" 2>/dev/null; then ok "$s reiniciado"; else err "$s FALHOU (veja opção 7 - Logs)"; fi
    else
      warn "$s não existe neste sistema — pulado"
    fi
  done
  echo
  warn "OpenVPN/PPPoE: reinicie pelo painel ou 'systemctl restart openvpn-server@mundix' / 'mundix-pppoe@*'."
  pause
}

act_logs() {
  echo "=== Logs ==="
  local opts=(mundix-dashboard-api mundix-siem-ingest mundix-active-response
              nftables dnsmasq nginx suricata clickhouse-server)
  local i
  for i in "${!opts[@]}"; do printf "  %d) %s\n" "$((i+1))" "${opts[$i]}"; done
  echo "  i) log do instalador (/var/log/mundix-install.log)"
  echo "  0) Voltar"
  read -rp "Escolha: " pick
  case "$pick" in
    0|"") return ;;
    i|I) tail -50 /var/log/mundix-install.log 2>/dev/null || warn "log do instalador não encontrado." ;;
    * )
      if [[ "$pick" =~ ^[0-9]+$ ]] && (( pick >= 1 && pick <= ${#opts[@]} )); then
        journalctl -u "${opts[$((pick-1))]}" -n 50 --no-pager 2>/dev/null || true
      else
        warn "opção inválida."
      fi ;;
  esac
  pause
}

act_connectivity() {
  echo "=== Testes de conectividade ==="
  local gw; gw="$(ip route show default 2>/dev/null | awk 'NR==1{print $3}')"
  if [[ -n "$gw" ]]; then
    ping -c2 -W2 "$gw" >/dev/null 2>&1 && ok "gateway $gw: alcançável" || err "gateway $gw: SEM resposta"
  else
    err "sem rota default configurada"
  fi
  ping -c2 -W2 8.8.8.8 >/dev/null 2>&1 && ok "internet (8.8.8.8): OK" || err "internet (8.8.8.8): FALHOU"
  if getent hosts github.com >/dev/null 2>&1; then ok "DNS: resolvendo"; else err "DNS: FALHOU"; fi
  pause
}

act_restore() {
  echo "=== Restaurar backup ==="
  local dir="${MUNDIX_ROOT}/backups"
  mapfile -t bks < <(ls -t "${dir}"/*.tar.gz 2>/dev/null)
  if ((${#bks[@]} == 0)); then err "nenhum backup em ${dir}/"; pause; return; fi
  local i
  for i in "${!bks[@]}"; do printf "  %d) %s\n" "$((i+1))" "$(basename "${bks[$i]}")"; done
  echo "  0) Voltar"
  read -rp "Restaurar qual? " pick
  [[ "$pick" =~ ^[0-9]+$ ]] && (( pick >= 1 && pick <= ${#bks[@]} )) || return
  echo
  warn "O restore cria um snapshot pre-restore automático (rollback) em ${dir}/"
  warn "Sem '--apply-network' e sem '--with-clickhouse' por padrão (rede se ajusta depois, na opção 4)."
  read -rp "Confirmar restore de $(basename "${bks[$((pick-1))]}")? [s/N] " c
  [[ "$c" =~ ^[sS]$ ]] || { echo "cancelado."; pause; return; }
  "${MUNDIX_ROOT}/scripts/ops/mundix-restore.sh" "${bks[$((pick-1))]}" || err "restore retornou erro (veja acima)."
  pause
}

act_power() {
  echo "=== Energia ==="
  echo "1) Reiniciar o appliance"
  echo "2) Desligar o appliance"
  echo "0) Voltar"
  read -rp "Escolha: " pick
  case "$pick" in
    1) read -rp "Confirmar REINICIALIZAÇÃO? [s/N] " c; [[ "$c" =~ ^[sS]$ ]] && systemctl reboot ;;
    2) read -rp "Confirmar DESLIGAMENTO? [s/N] " c; [[ "$c" =~ ^[sS]$ ]] && systemctl poweroff ;;
  esac
}

# -------------------------------------------------------------------- loop ---

require_root
while true; do
  clear 2>/dev/null || true
  cat <<EOF
${C_BOLD}${C_BLU}╔══════════════════════════════════════════════════════════════╗
║          Mundix Security 360 — Console de Recuperação         ║
║          versão ${VERSION}                                        ║
╚══════════════════════════════════════════════════════════════╝${C_NC}
EOF
  cat <<EOF
  1) Status geral (healthcheck + serviços)
  2) Interfaces de rede (links, IPs, papéis, PPPoE)
  3) Configurar LAN de gestão (IP fixo + DHCP, estilo pfSense)
  4) Aplicar rede / recarregar firewall
  5) Recuperar acesso ao painel (senha do admin)
  6) Reiniciar serviços
  7) Logs
  8) Testes de conectividade
  9) Restaurar backup
 10) Energia (reiniciar/desligar)
  0) Sair para o shell
EOF
  echo
  read -rp "Opção: " opt
  echo
  case "$opt" in
    1) act_status ;;
    2) act_interfaces ;;
    3) act_config_lan ;;
    4) act_apply_network ;;
    5) act_recover_access ;;
    6) act_restart_services ;;
    7) act_logs ;;
    8) act_connectivity ;;
    9) act_restore ;;
    10) act_power ;;
    0|q|Q|sair) echo "Saindo para o shell. (Reabra com: mundix-menu)"; exit 0 ;;
    *) warn "opção inválida."; sleep 1 ;;
  esac
done
