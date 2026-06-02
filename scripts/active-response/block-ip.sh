#!/bin/bash
set -euo pipefail

BLOCKLIST_FILE="/opt/mundix360/data/siem/blocklist/blocked.txt"
LOG_FILE="/opt/mundix360/data/siem/blocklist/block-ip.log"
ACTION="${1:-}"
IP="${2:-}"
DURATION="${3:-3600}"
REASON="${4:-active-response}"

log() {
    echo "$(date -Iseconds) $*" >> "$LOG_FILE"
}

validate_ip() {
    local ip="$1"
    if [[ "$ip" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
        IFS='.' read -ra OCTETS <<< "$ip"
        for octet in "${OCTETS[@]}"; do
            if (( octet > 255 )); then
                return 1
            fi
        done
        if [[ "$ip" == "127.0.0.1" ]]; then
            return 1
        fi
        return 0
    fi
    return 1
}

block() {
    if ! validate_ip "$IP"; then
        log "ERROR: Invalid IP $IP"
        exit 1
    fi

    if nft list table ip mundix_blocklist 2>/dev/null | grep -q "$IP"; then
        log "SKIP: $IP already blocked"
        exit 0
    fi

    nft add element ip mundix_blocklist blocked_ips { "$IP"} 2>/dev/null || \
    nft add set ip mundix_blocklist blocked_ips { type ipv4_addr\; } && \
    nft add element ip mundix_blocklist blocked_ips { "$IP"}

    UNBLOCK_TIME=$(date -d "+$DURATION seconds" -Iseconds 2>/dev/null || date -d "$DURATION seconds" -Iseconds)
    echo "$IP|$UNBLOCK_TIME|$REASON" >> "$BLOCKLIST_FILE"

    log "BLOCKED: $IP for ${DURATION}s reason=$REASON"
}

unblock() {
    if ! validate_ip "$IP"; then
        log "ERROR: Invalid IP $IP"
        exit 1
    fi

    nft delete element ip mundix_blocklist blocked_ips { "$IP"} 2>/dev/null || true
    grep -v "^$IP|" "$BLOCKLIST_FILE" > "$BLOCKLIST_FILE.tmp" 2>/dev/null || true
    mv "$BLOCKLIST_FILE.tmp" "$BLOCKLIST_FILE" 2>/dev/null || true

    log "UNBLOCKED: $IP"
}

cleanup() {
    local now=$(date +%s)
    local updated=0

    while IFS='|' read -r ip unblock_time reason; do
        if [[ -n "$unblock_time" ]]; then
            unblock_ts=$(date -d "$unblock_time" +%s 2>/dev/null || echo 9999999999)
            if (( now > unblock_ts )); then
                nft delete element ip mundix_blocklist blocked_ips { "$IP"} 2>/dev/null || true
                log "EXPIRED: $ip (was blocked until $unblock_time)"
                updated=1
            else
                echo "$ip|$unblock_time|$reason" >> "$BLOCKLIST_FILE.tmp"
            fi
        fi
    done < "$BLOCKLIST_FILE" 2>/dev/null || true

    if (( updated )); then
        mv "$BLOCKLIST_FILE.tmp" "$BLOCKLIST_FILE"
    fi
}

status() {
    echo "=== Active Blocklist ==="
    if [[ -f "$BLOCKLIST_FILE" ]]; then
        cat "$BLOCKLIST_FILE"
    else
        echo "(empty)"
    fi
    echo ""
    echo "=== nftables set ==="
    nft list set ip mundix_blocklist blocked_ips 2>/dev/null || echo "(set not initialized)"
}

case "$ACTION" in
    add)    block ;;
    delete) unblock ;;
    cleanup) cleanup ;;
    status) status ;;
    *)
        echo "Usage: $0 {add|delete|cleanup|status} <IP> [duration_seconds] [reason]"
        exit 1
        ;;
esac

exit 0
