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
    # Single `systemctl show` call returns load/active/unit-file state at once
    # (cheaper than three separate is-active/is-enabled calls on this 2-core box).
    # `--value` prints one value per line, in the order the -p flags are given.
    r = shell.run(
        ["systemctl", "show", "-p", "LoadState", "-p", "ActiveState",
         "-p", "UnitFileState", "--value", name],
        timeout=8,
    )
    lines = (r.stdout or "").splitlines()
    load = (lines[0].strip() if len(lines) > 0 else "") or "unknown"
    active = (lines[1].strip() if len(lines) > 1 else "") or "unknown"
    enabled = (lines[2].strip() if len(lines) > 2 else "") or "unknown"
    return {
        "name": name,
        "active": active,
        "enabled": enabled,
        "running": active == "active",
        # LoadState == "loaded" means the unit is actually installed on this host;
        # "not-found" means we ship support for it but it isn't provisioned here.
        "installed": load == "loaded",
    }


def all_services() -> list[dict[str, Any]]:
    # Only surface services actually installed on this appliance, so the operator
    # isn't confused by platform units we support but haven't provisioned here.
    # PLATFORM_SERVICES stays the canonical superset; one installed later will
    # appear automatically without a code change.
    return [st for s in PLATFORM_SERVICES if (st := service_status(s))["installed"]]


def control_service(name: str, action: str) -> dict[str, Any]:
    if name not in PLATFORM_SERVICES:
        raise ValueError(f"unknown service: {name}")
    if action not in {"restart", "reload", "start", "stop", "reload-or-restart"}:
        raise ValueError(f"invalid action: {action}")
    res = shell.run(["systemctl", action, name], timeout=30)
    return {
        "ok": res.ok,
        "name": name,
        "action": action,
        "stderr": res.stderr.strip(),
        "status": service_status(name),
    }


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


def _default_route_iface() -> str | None:
    """Interface carrying the default route — the most reliable WAN heuristic."""
    res = shell.run(["ip", "-o", "route", "show", "default"], timeout=8)
    for line in res.stdout.strip().splitlines():
        parts = line.split()
        if "dev" in parts:
            return parts[parts.index("dev") + 1]
    return None


def interfaces() -> list[dict[str, Any]]:
    """Enumerate every physical/virtual NIC on the host (excluding loopback) with
    its operational state, MAC and IPv4 addresses. Detected dynamically so the
    appliance adapts to whatever interfaces exist on each deployment — never
    hardcoded. The interface holding the default route is flagged as the WAN."""
    wan = _default_route_iface()

    # Map iface -> list of CIDR addresses (an interface may have several).
    addrs: dict[str, list[str]] = {}
    res_addr = shell.run(["ip", "-o", "-4", "addr", "show"], timeout=8)
    for line in res_addr.stdout.strip().splitlines():
        parts = line.split()
        if len(parts) >= 4:
            addrs.setdefault(parts[1], []).append(parts[3])

    out: list[dict[str, Any]] = []
    res_link = shell.run(["ip", "-o", "link", "show"], timeout=8)
    for line in res_link.stdout.strip().splitlines():
        # Format: "2: ens18: <BROADCAST,...> mtu 1500 ... state UP ... link/ether <mac> ..."
        parts = line.split()
        if len(parts) < 2:
            continue
        name = parts[1].rstrip(":").split("@")[0]
        if name == "lo":
            continue
        state = "unknown"
        if "state" in parts:
            state = parts[parts.index("state") + 1].lower()
        mac = ""
        for token in ("link/ether", "link/none"):
            if token in parts:
                idx = parts.index(token)
                if token == "link/ether" and idx + 1 < len(parts):
                    mac = parts[idx + 1]
                break
        iface_addrs = addrs.get(name, [])
        out.append({
            "interface": name,
            # Keep a flat 'address' for backward compatibility (first CIDR).
            "address": iface_addrs[0] if iface_addrs else None,
            "addresses": iface_addrs,
            "state": state,
            "mac": mac,
            "is_wan": name == wan,
        })
    # Stable, friendly ordering: WAN first, then up interfaces, then by name.
    out.sort(key=lambda i: (not i["is_wan"], i["state"] != "up", i["interface"]))
    return out

