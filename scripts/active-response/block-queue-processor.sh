#!/bin/bash
# Mundix360 Active Response - Queue processor
# Watch block-queue*.jsonl files and call block-ip.sh for each critical alert.
set -uo pipefail

QUEUE_DIR="/opt/mundix360/data/siem/blocklist"
PROCESSED_DIR="${QUEUE_DIR}/processed"
BLOCK_SCRIPT="/opt/mundix360/scripts/active-response/block-ip.sh"
LOG_FILE="${QUEUE_DIR}/processor.log"

mkdir -p "$PROCESSED_DIR"

log() { echo "$(date -Iseconds) $*" >> "$LOG_FILE"; }

process_file() {
    local f="$1"
    local count=0
    while IFS= read -r line; do
        ip=$(echo "$line" | grep -oP '"block_ip"\s*:\s*"\K[^"]+' 2>/dev/null || true)
        dur=$(echo "$line" | grep -oP '"block_duration"\s*:\s*\K[0-9]+' 2>/dev/null || true)
        reason=$(echo "$line" | grep -oP '"block_reason"\s*:\s*"\K[^"]+' 2>/dev/null || true)
        if [[ -n "$ip" && "$ip" != "null" ]]; then
            dur=${dur:-3600}
            reason=${reason:-siem-block}
            $BLOCK_SCRIPT add "$ip" "$dur" "$reason" >> "$LOG_FILE" 2>&1
            count=$((count + 1))
        fi
    done < "$f"
    if (( count > 0 )); then
        log "Processed $count blocks from $(basename "$f")"
    fi
    mv "$f" "${PROCESSED_DIR}/$(basename "$f").done"
}

log "Active response processor started"

while true; do
    for f in "${QUEUE_DIR}"/block-queue-*.jsonl; do
        [ -f "$f" ] || continue
        if [ "$(stat -c %s "$f" 2>/dev/null || echo 0)" -gt 0 ]; then
            # wait for vector to finish writing (>3s since last write)
            last_mod=$(stat -c %Y "$f" 2>/dev/null || echo 0)
            now=$(date +%s)
            if (( now - last_mod >= 3 )); then
                process_file "$f"
            fi
        fi
    done
    sleep 5
done
