#!/usr/bin/env bash
# =============================================================================
# mundix-upgrade.sh — Canal de atualizações ESTÁVEIS do Mundix Security 360.
#
# O canal é um repositório APT assinado (GitHub Pages) contendo APENAS o
# pacote mundix360 — instalação nova continua via ISO/bundle/instalador.
#
#   deb [signed-by=/usr/share/keyrings/mundix-repo.gpg] \
#       https://k0k4.github.io/mundix360-repo stable main
#
# Usado tanto pela CLI (sudo scripts/ops/mundix-upgrade.sh) quanto pelo
# PAINEL (Sistema → Atualizações): o backend o dispara via systemd-run, numa
# unit transitória própria, porque o upgrade REINICIA a própria API (um filho
# nohup da API morreria no systemctl restart — KillMode=control-group).
#
# Modos:
#   --check           compara versão instalada × versão do canal e imprime
#                     "atual=X canal=Y". Saída: 0 = há update, 1 = em dia,
#                     2 = canal inalcançável.
#   --setup-channel   instala a chave e a sources.list do canal (idempotente).
#   (padrão) | --yes  executa o upgrade completo (requer root).
#
# Log completo: /var/log/mundix-upgrade.log
# NUNCA roda `netplan apply` — a rede não é tocada pelo upgrade.
#
# A URL base do canal pode ser sobrescrita (testes) com MUNDIX_UPDATE_URL.
# =============================================================================
set -euo pipefail

BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MANIFEST="${BASE}/installer/manifest.env"
LOG="/var/log/mundix-upgrade.log"

UPDATE_URL="${MUNDIX_UPDATE_URL:-https://k0k4.github.io/mundix360-repo}"
UPDATE_URL="${UPDATE_URL%/}"
KEYRING="/usr/share/keyrings/mundix-repo.gpg"
SRCLIST="/etc/apt/sources.list.d/mundix360.list"
SRCLINE="deb [signed-by=${KEYRING}] ${UPDATE_URL} stable main"

if [[ -t 1 ]]; then
  C0=$'\e[0m'; CB=$'\e[34m'; CG=$'\e[32m'; CY=$'\e[33m'; CR=$'\e[31m'
else
  C0=""; CB=""; CG=""; CY=""; CR=""
fi
_log_init() { mkdir -p "$(dirname "$LOG")" 2>/dev/null || true; }
log()  { printf '%s[mundix-upgrade]%s %s\n' "$CB" "$C0" "$*" | tee -a "$LOG"; }
ok()   { printf '%s[ ok ]%s %s\n' "$CG" "$C0" "$*" | tee -a "$LOG"; }
warn() { printf '%s[warn]%s %s\n' "$CY" "$C0" "$*" | tee -a "$LOG" >&2; }
err()  { printf '%s[fail]%s %s\n' "$CR" "$C0" "$*" | tee -a "$LOG" >&2; }
die()  { err "$*"; echo "Log completo: ${LOG}" >&2; exit 1; }

# ------------------------------------------------------------ versões --------
installed_version() {
  sed -n 's/^MUNDIX_VERSION="\([^"]*\)".*/\1/p' "$MANIFEST" | head -1
}

# ver_gt A B => 0 se A > B, comparando TUPLAS NUMÉRICAS (1.10.0 > 1.2.0;
# comparação lexicográfica daria o contrário). Componentes ausentes contam 0.
ver_gt() {
  local a="$1" b="$2" i n x y
  local -a A B
  IFS='.' read -ra A <<<"$a"
  IFS='.' read -ra B <<<"$b"
  n=$(( ${#A[@]} > ${#B[@]} ? ${#A[@]} : ${#B[@]} ))
  for (( i=0; i<n; i++ )); do
    x="${A[i]:-0}"; y="${B[i]:-0}"
    [[ "$x" =~ ^[0-9]+$ ]] || x=0
    [[ "$y" =~ ^[0-9]+$ ]] || y=0
    (( 10#$x > 10#$y )) && return 0
    (( 10#$x < 10#$y )) && return 1
  done
  return 1
}

do_check() {
  local atual canal
  atual="$(installed_version)"
  [[ -n "$atual" ]] || { echo "atual=desconhecida canal=?"; return 2; }
  if ! canal="$(curl -fsS -m 15 "${UPDATE_URL}/version" 2>/dev/null | tr -d '[:space:]')" \
     || [[ -z "$canal" ]]; then
    echo "atual=${atual} canal=inalcançável"
    return 2
  fi
  echo "atual=${atual} canal=${canal}"
  if ver_gt "$canal" "$atual"; then
    echo "há atualização disponível"
    return 0
  fi
  echo "você está na estável mais recente"
  return 1
}

# ------------------------------------------------------------- canal ---------
setup_channel() {
  local key="${BASE}/installer/config/mundix-repo.gpg"
  if [[ ! -s "$key" ]]; then
    err "chave do canal não encontrada: ${key}"
    return 1
  fi
  install -m 0644 "$key" "$KEYRING"
  ok "chave do canal instalada: ${KEYRING}"
  # Idempotente: só regrava a sources.list se o conteúdo divergir.
  if [[ "$(cat "$SRCLIST" 2>/dev/null || true)" != "$SRCLINE" ]]; then
    printf '%s\n' "$SRCLINE" > "${SRCLIST}.tmp" && mv "${SRCLIST}.tmp" "$SRCLIST"
    chmod 0644 "$SRCLIST"
    ok "canal configurado: ${SRCLIST}"
  else
    log "sources.list já está correta (${SRCLIST})"
  fi
}

# ------------------------------------------------------------- upgrade -------
do_upgrade() {
  [[ "$(id -u)" == "0" ]] || die "execute como root (sudo)."
  : >>"$LOG"
  log "===== upgrade iniciado em $(date -Is) ====="

  local atual
  atual="$(installed_version)"
  log "versão instalada: ${atual:-desconhecida}"

  if [[ ! -e "$SRCLIST" || ! -e "$KEYRING" ]]; then
    log "canal ainda não configurado — semeando agora"
    setup_channel || die "falha ao configurar o canal de atualizações."
  fi

  # apt restrito à NOSSA lista: o canal é leve e não carrega o fecho de
  # dependências — as deps do pacote já estão instaladas no appliance.
  log "apt-get update (somente o canal mundix360)…"
  DEBIAN_FRONTEND=noninteractive apt-get update \
    -o Dir::Etc::sourcelist="sources.list.d/mundix360.list" \
    -o Dir::Etc::sourceparts="-" \
    -o APT::Get::List-Cleanup="0" >>"$LOG" 2>&1 \
    || die "apt-get update falhou — canal inalcançável? (veja ${LOG})"

  # Primeira adoção do canal: máquinas instaladas por git clone/ISO não têm o
  # pacote instalado, e `--only-upgrade` nesse caso NÃO instalaria nada.
  local -a only=()
  if dpkg-query -W -f='${Status}' mundix360 2>/dev/null | grep -q '^install ok installed$'; then
    log "apt-get install --only-upgrade mundix360…"
    only=(--only-upgrade)
  else
    log "pacote mundix360 ainda não instalado — primeira adoção do canal (install completo)…"
  fi
  # O postinst roda o instalador (--skip-apt --skip-frontend --upgrade):
  # o frontend NÃO é rebuildado no alvo porque o dist/ pré-buildado já VEM no
  # pacote (build-deb.sh exige dist/index.html no payload), e o próprio
  # postinst reinicia os serviços (phase_services). Não há o que rebuildar
  # aqui — appliances de ISO/bundle nem sequer têm npm instalado.
  DEBIAN_FRONTEND=noninteractive apt-get install -y "${only[@]}" mundix360 >>"$LOG" 2>&1 \
    || die "falha no upgrade do pacote (veja ${LOG}). Considere rollback: scripts/ops/mundix-restore.sh <backup> ou snapshot da VM."

  ok "pacote atualizado"

  # Rede de segurança: o postinst já reiniciou API e nginx; só intervimos se
  # algo não estiver de pé (evita uma segunda janela de indisponibilidade).
  if ! systemctl is-active --quiet mundix-dashboard-api.service; then
    warn "API não estava ativa após o upgrade — reiniciando"
    systemctl restart mundix-dashboard-api.service >>"$LOG" 2>&1 || true
  fi
  if nginx -t >>"$LOG" 2>&1; then
    systemctl reload nginx >>"$LOG" 2>&1 || true
  else
    warn "nginx -t falhou após o upgrade — reload NÃO executado (veja ${LOG})"
  fi

  local nova
  nova="$(installed_version)"
  log "===== upgrade finalizado em $(date -Is): ${atual:-?} -> ${nova:-?} ====="

  # Healthcheck final (best-effort) + verificação dura da API do painel.
  local hc_ok=1
  if [[ -x "${BASE}/scripts/ops/mundix360-healthcheck.sh" ]]; then
    log "healthcheck pós-upgrade…"
    "${BASE}/scripts/ops/mundix360-healthcheck.sh" >>"$LOG" 2>&1 || hc_ok=0
  fi
  local api_ok=0
  for _ in $(seq 1 30); do
    if curl -fsS -m 3 -o /dev/null "http://127.0.0.1:8100/health" 2>/dev/null; then
      api_ok=1; break
    fi
    sleep 1
  done
  if [[ "$api_ok" != "1" ]]; then
    hc_ok=0
    err "API do painel não respondeu após o upgrade."
  fi

  if [[ "$hc_ok" == "1" ]]; then
    ok "upgrade concluído com sucesso: versão ${nova:-?}"
    echo "Log completo: ${LOG}"
    return 0
  fi
  err "upgrade aplicado (${atual:-?} -> ${nova:-?}), mas a verificação final falhou."
  err "Avalie o log ${LOG} e, se necessário, faça rollback com:"
  err "  sudo ${BASE}/scripts/ops/mundix-restore.sh <backup.tar.gz>   (ou restaure o snapshot da VM)"
  return 1
}

# ------------------------------------------------------------------ main -----
_log_init
MODE="${1:-}"
case "$MODE" in
  --check)         do_check ;;
  --setup-channel) [[ "$(id -u)" == "0" ]] || die "execute como root (sudo)."
                   setup_channel ;;
  ""|--yes|-y)     do_upgrade ;;
  -h|--help)       sed -n '2,33p' "$0" ;;
  *) echo "opção desconhecida: $MODE" >&2; exit 2 ;;
esac
