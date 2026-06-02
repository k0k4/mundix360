"""System & service status via systemd and basic host metrics."""
from __future__ import annotations

import os
import shutil
from typing import Any

from . import shell

# Services that make up the Mundix360 platform.
PLATFORM_SERVICES = [
    "nftables", "dnsmasq", "suricata",
    "victoriametrics", "loki", "vector", "grafana-server",
    "kafka", "clickhouse-server", "valkey-server",
    "akvorado-inlet", "akvorado-outlet", "akvorado-console",
    "akvorado-orchestrator",
    "mundix-active-response", "mundix-triage.timer",
]


def service_status(name: str) -> dict[str, Any]:
    active = shell.run(["systemctl", "is-active", name], timeout=8)
    enabled = shell.run(["systemctl", "is-enabled", name], timeout=8)
    return {
        "name": name,
        "active": active.stdout.strip() or "unknown",
        "enabled": enabled.stdout.strip() or "unknown",
        "running": active.stdout.strip() == "active",
    }


def all_services() -> list[dict[str, Any]]:
    return [service_status(s) for s in PLATFORM_SERVICES]


def host_metrics() -> dict[str, Any]:
    # CPU load
    load1 = load5 = load15 = 0.0
    try:
        load1, load5, load15 = os.getloadavg()
    except OSError:
        pass

    # Memory
    mem_total = mem_avail = 0
    try:
        with open("/proc/meminfo") as f:
            info = {}
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    info[parts[0].strip()] = int(parts[1].strip().split()[0])
        mem_total = info.get("MemTotal", 0)
        mem_avail = info.get("MemAvailable", 0)
    except OSError:
        pass
    mem_used = mem_total - mem_avail

    # Disk
    disk = shutil.disk_usage("/")

    # CPU count
    cpu_count = os.cpu_count() or 1

    return {
        "load": {"1m": round(load1, 2), "5m": round(load5, 2), "15m": round(load15, 2)},
        "cpu_count": cpu_count,
        "load_pct": round(min(load1 / cpu_count * 100, 100), 1) if cpu_count else 0,
        "memory": {
            "total_kb": mem_total,
            "used_kb": mem_used,
            "available_kb": mem_avail,
            "used_pct": round(mem_used / mem_total * 100, 1) if mem_total else 0,
        },
        "disk": {
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
            "used_pct": round(disk.used / disk.total * 100, 1) if disk.total else 0,
        },
    }


def interfaces() -> list[dict[str, Any]]:
    res = shell.run(["ip", "-o", "-4", "addr", "show"], timeout=8)
    out: list[dict[str, Any]] = []
    for line in res.stdout.strip().splitlines():
        parts = line.split()
        if len(parts) >= 4:
            out.append({"interface": parts[1], "address": parts[3]})
    return out
