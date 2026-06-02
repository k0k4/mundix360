"""Network/VLAN/DHCP management derived from dnsmasq zone configs."""
from __future__ import annotations

import os
import re
from typing import Any

from ..config import settings

# Static description of zones <-> interfaces (matches nftables.conf / dnsmasq).
ZONE_INTERFACES = {
    "lan": {"iface": "ens19", "net": "192.168.0.0/24"},
    "dmz": {"iface": "ens20", "net": "10.0.0.0/8"},
    "iot": {"iface": "ens21", "net": "172.16.0.0/16"},
}


def _parse_dnsmasq_conf(path: str) -> dict[str, Any]:
    conf: dict[str, Any] = {"raw": {}, "dhcp_range": None, "options": {}}
    if not os.path.isfile(path):
        return conf
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key, val = key.strip(), val.strip()
                if key == "dhcp-range":
                    conf["dhcp_range"] = val
                elif key == "dhcp-option":
                    conf["options"].setdefault("dhcp-option", []).append(val)
                else:
                    conf["raw"][key] = val
            else:
                conf["raw"][line] = True
    return conf


def list_zones() -> list[dict[str, Any]]:
    zones = []
    for name, meta in ZONE_INTERFACES.items():
        path = os.path.join(settings.dnsmasq_dir, f"{name}.conf")
        conf = _parse_dnsmasq_conf(path)
        dhcp_range = conf.get("dhcp_range")
        start = end = lease = None
        if dhcp_range:
            parts = dhcp_range.split(",")
            if len(parts) >= 2:
                start, end = parts[0], parts[1]
            if len(parts) >= 4:
                lease = parts[3]
        zones.append({
            "zone": name,
            "interface": meta["iface"],
            "network": meta["net"],
            "listen_address": conf["raw"].get("listen-address"),
            "domain": conf["raw"].get("domain"),
            "dhcp_start": start,
            "dhcp_end": end,
            "lease_time": lease,
            "upstream_dns": [v for k, v in conf["raw"].items() if k == "server"],
            "config_present": os.path.isfile(path),
        })
    return zones


_LEASE_RE = re.compile(r"^(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)")


def dhcp_leases() -> list[dict[str, Any]]:
    leases: list[dict[str, Any]] = []
    path = settings.dhcp_leases_file
    if not os.path.isfile(path):
        return leases
    with open(path) as f:
        for line in f:
            m = _LEASE_RE.match(line.strip())
            if not m:
                continue
            expiry, mac, ip, hostname, client_id = m.groups()
            zone = _zone_for_ip(ip)
            leases.append({
                "expiry": int(expiry),
                "mac": mac,
                "ip": ip,
                "hostname": None if hostname == "*" else hostname,
                "client_id": None if client_id == "*" else client_id,
                "zone": zone,
            })
    return leases


def _zone_for_ip(ip: str) -> str | None:
    try:
        import ipaddress

        addr = ipaddress.ip_address(ip)
        for name, meta in ZONE_INTERFACES.items():
            if addr in ipaddress.ip_network(meta["net"]):
                return name
    except ValueError:
        pass
    return None
