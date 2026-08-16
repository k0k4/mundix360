#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; }

echo "╔══════════════════════════════════════════╗"
echo "║   Mundix Security 360 - Health Check    ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "Date: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo ""

echo "--- NETWORK ---"
# NICs físicas detectadas dinamicamente (sem hardcode de nomes).
mapfile -t HC_IFACES < <(ip -o link show 2>/dev/null | awk -F': ' '{print $2}' \
    | grep -vE '^(lo|veth|docker|br-|vnet|tun|tap|wg|virbr|ppp)' | sed 's/@.*//' | sort -u)
if [ "${#HC_IFACES[@]}" -eq 0 ]; then
    fail "nenhuma interface física detectada"
fi
for iface in "${HC_IFACES[@]}"; do
    if ip link show "$iface" 2>/dev/null | grep -q "state UP"; then
        ip_addr=$(ip -4 addr show "$iface" 2>/dev/null | grep -oP 'inet \K[^ ]+' || echo "no-ip")
        ok "$iface: UP ($ip_addr)"
    else
        fail "$iface: DOWN"
    fi
done
echo ""

echo "--- SERVICES ---"
for svc in nftables dnsmasq suricata ssh; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        ok "$svc: running"
    elif systemctl is-active --quiet "${svc}.service" 2>/dev/null; then
        ok "$svc: running"
    else
        fail "$svc: not running"
    fi
done

for svc in systemd-resolved; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        warn "$svc: running (should be disabled)"
    else
        ok "$svc: disabled (correct)"
    fi
done
echo ""

echo "--- CONTAINERS (Podman) ---"
if command -v podman &>/dev/null; then
    containers=$(podman ps --format '{{.Names}}\t{{.Status}}' 2>/dev/null || true)
    if [ -n "$containers" ]; then
        echo "$containers" | while IFS=$'\t' read -r name status; do
            ok "container $name: $status"
        done
    else
        warn "No containers running"
    fi
else
    fail "Podman not installed"
fi
echo ""

echo "--- DNS ---"
if dig @127.0.0.1 github.com +short +time=3 &>/dev/null; then
    ok "DNS resolution: working"
else
    fail "DNS resolution: failed"
fi

# Testa o dnsmasq em cada IP local (LAN/DMZ/etc.), sem hardcode de endereços.
while read -r lip; do
    [ -n "$lip" ] || continue
    if dig @"$lip" github.com +short +time=3 &>/dev/null; then
        ok "DNS em $lip: working"
    else
        warn "DNS em $lip: not reachable"
    fi
done < <(ip -4 -o addr show scope global 2>/dev/null | awk '{split($4,a,"/"); print a[1]}' | grep -v '^127\.')
echo ""

echo "--- SURICATA ---"
if systemctl is-active --quiet suricata 2>/dev/null; then
    rules_count=$(wc -l < /var/lib/suricata/rules/suricata.rules 2>/dev/null || echo "0")
    ok "Suricata rules: $rules_count"
fi
echo ""

echo "--- DISK ---"
disk_usage=$(df -h / | awk 'NR==2{print $5}' | tr -d '%')
if [ "$disk_usage" -lt 80 ]; then
    ok "Disk usage: ${disk_usage}%"
elif [ "$disk_usage" -lt 90 ]; then
    warn "Disk usage: ${disk_usage}%"
else
    fail "Disk usage: ${disk_usage}%"
fi
echo ""

echo "--- MEMORY ---"
mem_total=$(free -m | awk '/Mem:/{print $2}')
mem_used=$(free -m | awk '/Mem:/{print $3}')
mem_pct=$((mem_used * 100 / mem_total))
if [ "$mem_pct" -lt 80 ]; then
    ok "Memory: ${mem_used}MB / ${mem_total}MB (${mem_pct}%)"
elif [ "$mem_pct" -lt 90 ]; then
    warn "Memory: ${mem_used}MB / ${mem_total}MB (${mem_pct}%)"
else
    fail "Memory: ${mem_used}MB / ${mem_total}MB (${mem_pct}%)"
fi
echo ""

echo "--- FW DROP LOG (last 5 entries) ---"
journalctl -u nftables --since "1 hour ago" 2>/dev/null | grep "NFT-INPUT-DROP\|NFT-FORWARD-DROP" | tail -5 || echo "(no drops in last hour)"
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║         Health Check Complete           ║"
echo "╚══════════════════════════════════════════╝"
