#!/bin/bash
# =============================================================================
# Mundix Security 360 — Restore de backup em linha de comando
#
# Uso pensado para recuperação de desastre (ex.: perda do acesso web após uma
# mudança de rede/firewall): restaura configs, estado do dashboard e serviços
# a partir de um mundix-backup-*.tar.gz gerado pelo módulo de backup.
#
#   ./mundix-restore.sh /opt/mundix360/backups/mundix-backup-XXXX.tar.gz [opções]
#
# Opções:
#   -y, --yes            não pede confirmação interativa
#   -n, --dry-run        só mostra o que seria restaurado (não altera nada)
#       --no-services    não para/inicia serviços (só restaura arquivos)
#       --apply-network  ao final, roda `netplan apply` e recarrega o nftables
#                        (PERIGOSO via sessão remota — use com console à mão)
#       --with-clickhouse  restaura também o histórico SIEM (ClickHouse)
#       --force          prossegue mesmo se a verificação de integridade falhar
#   -h, --help           esta ajuda
#
# Antes de sobrescrever qualquer arquivo, o script grava um snapshot dos
# arquivos atuais em  backups/pre-restore-<timestamp>.tar.gz  (rollback).
# =============================================================================
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="$BASE_DIR/dashboard/backend/data"
BACKUP_DIR="$BASE_DIR/backups"
ENV_FILE="$BASE_DIR/dashboard/backend/.env"

MUNDIX_SERVICES=(
    mundix-dashboard-api.service
    mundix-siem-ingest.service
    mundix-active-response.service
)
MUNDIX_TIMERS=(
    mundix-triage.timer
    mundix-suricata-update.timer
)
MUNDIX_ENABLE_ONLY=(
    mundix-triage.service
)

ASSUME_YES=0; DRY_RUN=0; NO_SERVICES=0; APPLY_NETWORK=0; WITH_CH=0; FORCE=0
ARCHIVE=""

log()  { echo "[INFO]  $*"; }
warn() { echo "[AVISO] $*" >&2; }
err()  { echo "[ERRO]  $*" >&2; }
die()  { err "$*"; exit 1; }

usage() { sed -n '2,23p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0; }

# ------------------------------------------------------------- argumentos ----
while [[ $# -gt 0 ]]; do
    case "$1" in
        -y|--yes)            ASSUME_YES=1 ;;
        -n|--dry-run)        DRY_RUN=1 ;;
        --no-services)       NO_SERVICES=1 ;;
        --apply-network)     APPLY_NETWORK=1 ;;
        --with-clickhouse)   WITH_CH=1 ;;
        --force)             FORCE=1 ;;
        -h|--help)           usage ;;
        -*)                  die "opção desconhecida: $1 (use --help)" ;;
        *)
            [[ -n "$ARCHIVE" ]] && die "informe apenas UM arquivo de backup"
            ARCHIVE="$1" ;;
    esac
    shift
done

[[ -z "$ARCHIVE" ]] && { usage; }
[[ $EUID -eq 0 ]] || die "rode como root"
[[ -f "$ARCHIVE" ]] || die "arquivo não encontrado: $ARCHIVE"
tar -tzf "$ARCHIVE" &>/dev/null || die "não é um tar.gz válido: $ARCHIVE"

STAGING="$(mktemp -d /tmp/mundix-restore.XXXXXX)"
cleanup() { rm -rf "$STAGING"; }
trap cleanup EXIT

# ------------------------------------------------------------ verificação ----
log "extraindo para área de staging: $STAGING"
tar -xzf "$ARCHIVE" -C "$STAGING"

[[ -f "$STAGING/manifest.json" ]] || die "manifest.json ausente — não parece um backup mundix360"
echo "------------------------------------------------------------"
python3 - "$STAGING/manifest.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
print(f"  Backup : {m.get('name')}")
print(f"  Criado : {m.get('created')}")
print(f"  Host   : {m.get('host')}")
print(f"  Itens  : {len(m.get('contents', []))} arquivos")
if m.get('clickhouse'):
    print(f"  SIEM   : tabela {m['clickhouse'].get('table')} ({m['clickhouse'].get('rows')} linhas)")
if m.get('clickhouse_error'):
    print(f"  SIEM   : (falhou no backup: {m['clickhouse_error']})")
PY
echo "------------------------------------------------------------"

MEMBERS="$(tar -tzf "$ARCHIVE")"
if [[ $FORCE -eq 0 ]] && ! grep -q '^configs/' <<<"$MEMBERS"; then
    die "arquivo sem seção configs/ — use --force se tiver certeza"
fi

if [[ $DRY_RUN -eq 1 ]]; then
    log "DRY-RUN — arquivos de configuração que seriam restaurados:"
    grep '^configs/' <<<"$MEMBERS" | sed 's|^configs/|  ->  |' | head -60 || true
    log "DRY-RUN — dados do dashboard que seriam restaurados:"
    grep '^data/' <<<"$MEMBERS" | sed 's|^|  ->  |' || true
    log "DRY-RUN — nenhuma alteração foi feita."
    exit 0
fi

# ------------------------------------------------------------ confirmação ----
if [[ $ASSUME_YES -eq 0 ]]; then
    echo
    warn "Isto vai SOBRESCREVER as configurações atuais do appliance."
    read -r -p "Continuar? [s/N] " ans
    [[ "${ans,,}" == "s" || "${ans,,}" == "sim" ]] || die "abortado pelo operador"
fi

# --------------------------------------------------- snapshot pré-restore ----
TS="$(date +%Y%m%d-%H%M%S)"
SNAP="$BACKUP_DIR/pre-restore-$TS.tar.gz"
log "gravando snapshot dos arquivos atuais em: $SNAP"
mkdir -p "$BACKUP_DIR"
SNAP_LIST="$(grep '^configs/' <<<"$MEMBERS" | sed 's|^configs/||' | while read -r p; do [[ -e "/$p" || -L "/$p" ]] && echo "$p"; done || true)"
if [[ -n "$SNAP_LIST" ]]; then
    tar -czf "$SNAP" -C / --ignore-failed-read $SNAP_LIST 2>/dev/null || true
fi
[[ -d "$DATA_DIR" ]] && tar -czf "$SNAP.data.tgz" -C "$DATA_DIR" . 2>/dev/null || true
chmod 600 "$SNAP" 2>/dev/null || true

# -------------------------------------------------------- parar serviços -----
pppoe_instances() {
    # Lista instâncias mundix-pppoe@<id> habilitadas no modelo salvo.
    python3 - <<'PY' 2>/dev/null || true
import json
try:
    for l in json.load(open("/etc/mundix/pppoe.json")).get("links", []):
        if l.get("enabled"):
            print(f"mundix-pppoe@{l['id']}.service")
except Exception:
    pass
PY
}
PPP_UNITS="$(pppoe_instances)"

if [[ $NO_SERVICES -eq 0 ]]; then
    log "parando serviços mundix (o dashboard ficará fora até o fim do restore)…"
    systemctl stop "${MUNDIX_TIMERS[@]}" 2>/dev/null || true
    systemctl stop "${MUNDIX_SERVICES[@]}" 2>/dev/null || true
    for u in $PPP_UNITS; do systemctl stop "$u" 2>/dev/null || true; done
fi

# ----------------------------------------------------------- restauração -----
if [[ -d "$STAGING/configs" ]]; then
    log "restaurando configs/ → /"
    cp -a "$STAGING/configs/." /
fi

if [[ -d "$STAGING/data" ]]; then
    log "restaurando data/ → $DATA_DIR"
    mkdir -p "$DATA_DIR"
    cp -a "$STAGING/data/." "$DATA_DIR/"
fi

# ---------------------------------------------------------- ClickHouse -------
if [[ $WITH_CH -eq 1 && -f "$STAGING/clickhouse/siem_alerts.native.gz" ]]; then
    log "restaurando histórico SIEM no ClickHouse…"
    python3 - "$STAGING/clickhouse" "$ENV_FILE" <<'PY' || warn "falha ao restaurar ClickHouse (configs não foram afetadas)"
import gzip, os, sys, urllib.parse, urllib.request

ch_dir, env_file = sys.argv[1], sys.argv[2]
env = {}
if os.path.isfile(env_file):
    for line in open(env_file):
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")

host = env.get("CLICKHOUSE_HOST", "127.0.0.1")
port = env.get("CLICKHOUSE_PORT", "8123")
db   = env.get("CLICKHOUSE_DB", "akvorado")
base = f"http://{host}:{port}/"

def query(q, data=None):
    url = base + "?" + urllib.parse.urlencode({"query": q})
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read().decode()

table = f"{db}.siem_alerts"
if query(f"EXISTS TABLE {table}").strip() != "1":
    schema = open(os.path.join(ch_dir, "siem_alerts.schema.sql")).read()
    # o arquivo veio de um SHOW CREATE em TSV: desescapa \n, \t, \\
    stmt = schema.strip().encode().decode("unicode_escape")
    query(stmt)
    print("[INFO]  tabela recriada a partir do schema do backup")

before = int(query(f"SELECT count() FROM {table}").strip())
with gzip.open(os.path.join(ch_dir, "siem_alerts.native.gz"), "rb") as f:
    payload = f.read()
url = base + "?" + urllib.parse.urlencode({"query": f"INSERT INTO {table} FORMAT Native"})
req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/octet-stream"})
with urllib.request.urlopen(req, timeout=600):
    pass
after = int(query(f"SELECT count() FROM {table}").strip())
print(f"[INFO]  ClickHouse: {before} -> {after} linhas em {table}")
PY
fi

# ------------------------------------------------------ serviços de volta ----
if [[ $NO_SERVICES -eq 0 ]]; then
    log "systemd: daemon-reload + reabilitando units mundix"
    systemctl daemon-reload
    for u in "${MUNDIX_ENABLE_ONLY[@]}" "${MUNDIX_SERVICES[@]}" "${MUNDIX_TIMERS[@]}"; do
        systemctl enable "$u" &>/dev/null || warn "não foi possível habilitar $u"
    done
    for u in $PPP_UNITS; do
        systemctl enable --now "$u" &>/dev/null || warn "falha ao subir $u (link físico presente?)"
    done
    log "subindo serviços mundix…"
    for u in "${MUNDIX_SERVICES[@]}" "${MUNDIX_TIMERS[@]}"; do
        systemctl start "$u" &>/dev/null || warn "falha ao iniciar $u"
    done
    # dnsmasq é seguro de recarregar e pega possíveis configs restauradas
    systemctl reload-or-restart dnsmasq 2>/dev/null || true
fi

if [[ $APPLY_NETWORK -eq 1 ]]; then
    warn "--apply-network: aplicando netplan (pode derrubar esta sessão!)"
    netplan apply || warn "netplan apply falhou — revise /etc/netplan"
    if nft -c -f /etc/nftables.conf &>/dev/null; then
        systemctl restart nftables && log "nftables recarregado"
    else
        warn "/etc/nftables.conf inválido — nftables NÃO foi recarregado"
    fi
else
    warn "configs de rede/firewall restauradas em disco, mas NÃO aplicadas."
    warn "quando estiver seguro (de preferência no console), rode:"
    warn "    netplan apply && systemctl restart nftables"
fi

# ------------------------------------------------------------- relatório -----
echo "============================================================"
log "restore concluído. estado dos serviços:"
for u in "${MUNDIX_SERVICES[@]}" "${MUNDIX_TIMERS[@]}" $PPP_UNITS; do
    st="$(systemctl is-active "$u" 2>/dev/null || true)"
    printf "    %-42s %s\n" "$u" "$st"
done
echo
log "rotas default atuais:"
ip route show default | sed 's/^/    /' || true
echo
log "snapshot pré-restore (rollback): $SNAP"
[[ -f "$SNAP.data.tgz" ]] && log "snapshot dos dados do dashboard: $SNAP.data.tgz"
echo "============================================================"
