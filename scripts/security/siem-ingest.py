#!/usr/bin/env python3
"""Suricata eve.json -> ClickHouse akvorado.siem_alerts ingester.

Lightweight replacement for the vector/kafka pipeline used by the full
observability profile. Tails Suricata's EVE JSON log, keeps only
``event_type: alert`` records, maps them onto the ``siem_alerts`` schema and
batch-inserts them into ClickHouse. A persisted byte offset lets the service
resume after a restart, and inode/size checks handle log rotation.

Runs under the appliance venv (clickhouse_connect) as the
``mundix-siem-ingest`` systemd service.
"""
from __future__ import annotations

import json
import os
import signal
import socket
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import clickhouse_connect

EVE_PATH = os.environ.get("MUNDIX_EVE_PATH", "/var/log/suricata/eve.json")
STATE_PATH = os.environ.get(
    "MUNDIX_EVE_STATE", "/opt/mundix360/data/siem/eve-ingest.offset.json"
)
LOG_PATH = os.environ.get(
    "MUNDIX_EVE_LOG", "/opt/mundix360/data/siem/siem-ingest.log"
)
CH_HOST = os.environ.get("MUNDIX_CLICKHOUSE_HOST", "127.0.0.1")
CH_PORT = int(os.environ.get("MUNDIX_CLICKHOUSE_PORT", "8123"))
CH_USER = os.environ.get("MUNDIX_CLICKHOUSE_USER", "default")
CH_PASSWORD = os.environ.get("MUNDIX_CLICKHOUSE_PASSWORD", "")
CH_DB = os.environ.get("MUNDIX_CLICKHOUSE_DB", "akvorado")
TABLE = "siem_alerts"

POLL_SECONDS = float(os.environ.get("MUNDIX_EVE_POLL", "2.0"))
BATCH_MAX = int(os.environ.get("MUNDIX_EVE_BATCH", "500"))
HOSTNAME = socket.gethostname()

# Suricata severity (1=high .. 3=low) mapped onto the dashboard's 0-10 scale,
# where the UI treats severity >= 3 as "high".
_SEV_MAP = {1: 8, 2: 5, 3: 3, 4: 2}

_COLUMNS = [
    "event_id", "timestamp", "source", "source_type", "rule_id", "rule_name",
    "severity", "category", "mitre_tactic", "mitre_technique", "src_ip",
    "dst_ip", "src_port", "dst_port", "protocol", "hostname", "user",
    "description", "full_log", "action_taken", "false_positive",
    "triage_notes", "tags",
]

_running = True


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _stop(_signum, _frame) -> None:
    global _running
    _running = False


def _load_state() -> dict[str, Any]:
    try:
        with open(STATE_PATH) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_state(inode: int, offset: int) -> None:
    tmp = STATE_PATH + ".tmp"
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(tmp, "w") as fh:
            json.dump({"inode": inode, "offset": offset}, fh)
        os.replace(tmp, STATE_PATH)
    except OSError as exc:
        log(f"WARN could not persist offset: {exc}")


def _parse_ts(raw: str) -> datetime:
    """Suricata timestamps are ISO-8601 with offset; return naive UTC."""
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _map_alert(ev: dict[str, Any], raw_line: str) -> list[Any] | None:
    if ev.get("event_type") != "alert":
        return None
    alert = ev.get("alert") or {}
    meta = alert.get("metadata") or {}
    tags: list[str] = []
    for key in ("tag", "affected_product", "attack_target"):
        val = meta.get(key)
        if isinstance(val, list):
            tags.extend(str(v) for v in val)
    mitre_tactic = ""
    mitre_technique = ""
    if isinstance(meta.get("mitre_tactic_id"), list):
        mitre_tactic = ", ".join(str(v) for v in meta["mitre_tactic_id"])
    if isinstance(meta.get("mitre_technique_id"), list):
        mitre_technique = ", ".join(str(v) for v in meta["mitre_technique_id"])

    return [
        uuid.uuid4(),
        _parse_ts(ev.get("timestamp", "")),
        "suricata",
        "ids",
        str(alert.get("signature_id", "")),
        str(alert.get("signature", "")),
        _SEV_MAP.get(_to_int(alert.get("severity")), 2),
        str(alert.get("category", "")),
        mitre_tactic,
        mitre_technique,
        str(ev.get("src_ip", "")),
        str(ev.get("dest_ip", "")),
        _to_int(ev.get("src_port")),
        _to_int(ev.get("dest_port")),
        str(ev.get("proto", "")),
        HOSTNAME,
        "",
        str(alert.get("signature", "")),
        raw_line[:65000],
        "",
        0,
        "",
        tags,
    ]


def _connect():
    return clickhouse_connect.get_client(
        host=CH_HOST, port=CH_PORT, username=CH_USER,
        password=CH_PASSWORD, database=CH_DB,
    )


def main() -> int:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    client = None
    while client is None and _running:
        try:
            client = _connect()
            client.query("SELECT 1")
        except Exception as exc:  # noqa: BLE001 - retry until ClickHouse is up
            log(f"waiting for ClickHouse: {exc}")
            client = None
            time.sleep(5)

    log(f"ingester started; following {EVE_PATH}")

    state = _load_state()
    offset = int(state.get("offset", 0))
    saved_inode = int(state.get("inode", 0))

    while _running:
        try:
            st = os.stat(EVE_PATH)
        except FileNotFoundError:
            time.sleep(POLL_SECONDS)
            continue

        # Detect rotation/truncation: new inode or file shrank below offset.
        if st.st_ino != saved_inode or st.st_size < offset:
            log(f"log rotated/truncated; restarting from 0 (inode {st.st_ino})")
            offset = 0
            saved_inode = st.st_ino

        if st.st_size <= offset:
            time.sleep(POLL_SECONDS)
            continue

        rows: list[list[Any]] = []
        with open(EVE_PATH, "r", errors="replace") as fh:
            fh.seek(offset)
            for line in fh:
                if not line.endswith("\n"):
                    # Partial final line — stop before it; revisit next poll.
                    break
                offset += len(line.encode("utf-8", "replace"))
                line = line.strip()
                if not line or '"event_type":"alert"' not in line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                mapped = _map_alert(ev, line)
                if mapped is not None:
                    rows.append(mapped)
                if len(rows) >= BATCH_MAX:
                    break

        if rows:
            try:
                client.insert(TABLE, rows, column_names=_COLUMNS)
                log(f"inserted {len(rows)} alert(s)")
            except Exception as exc:  # noqa: BLE001
                log(f"ERROR insert failed, will retry: {exc}")
                # Roll back offset advance for this batch by not saving it.
                try:
                    client = _connect()
                except Exception:
                    pass
                time.sleep(POLL_SECONDS)
                continue

        _save_state(saved_inode, offset)

        if not rows:
            time.sleep(POLL_SECONDS)

    log("ingester stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
