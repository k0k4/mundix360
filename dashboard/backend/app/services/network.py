"""Network/VLAN/DHCP management derived from dnsmasq zone configs.

Reads and writes live dnsmasq config files under /etc/dnsmasq.d. Mutations are
validated with `dnsmasq --test` before reloading the service.
"""
from __future__ import annotations

import ipaddress
import os
import re
from typing import Any

from ..config import settings
from . import shell

# Static description of zones <-> interfaces (matches nftables.conf / dnsmasq).
ZONE_INTERFACES = {
    "lan": {"iface": "ens19", "net": "192.168.0.0/24"},
    "dmz": {"iface": "ens20", "net": "10.0.0.0/8"},
    "iot": {"iface": "ens21", "net": "172.16.0.0/16"},
}

RESERVATIONS_FILE = "mundix-dhcp-reservations.conf"
ZONE_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,30}$")


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


def _parse_dnsmasq_conf(path: str) -> dict[str, Any]:
    conf: dict[str, Any] = {"raw": {}, "dhcp_range": None, "servers": [], "options": {}}
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
                elif key == "server":
                    conf["servers"].append(val)
                else:
                    conf["raw"][key] = val
            else:
                conf["raw"][line] = True
    return conf


def _zone_path(name: str) -> str:
    return os.path.join(settings.dnsmasq_etc_dir, f"{name}.conf")


def _zone_from_conf(name: str, path: str) -> dict[str, Any]:
    conf = _parse_dnsmasq_conf(path)
    meta = ZONE_INTERFACES.get(name, {})
    dhcp_range = conf.get("dhcp_range")
    start = end = netmask = lease = None
    if dhcp_range:
        parts = dhcp_range.split(",")
        if len(parts) >= 2:
            start, end = parts[0], parts[1]
        if len(parts) >= 3:
            netmask = parts[2]
        if len(parts) >= 4:
            lease = parts[3]
    gateway = None
    for opt in conf["options"].get("dhcp-option", []):
        if opt.startswith("3,"):
            gateway = opt.split(",", 1)[1]
    return {
        "zone": name,
        "id": name,
        "interface": conf["raw"].get("interface") or meta.get("iface"),
        "network": meta.get("net"),
        "listen_address": conf["raw"].get("listen-address"),
        "domain": conf["raw"].get("domain"),
        "gateway": gateway,
        "dhcp_start": start,
        "dhcp_end": end,
        "netmask": netmask,
        "lease_time": lease,
        "upstream_dns": conf["servers"],
        "builtin": name in ZONE_INTERFACES,
        "config_present": os.path.isfile(path),
    }


def _discover_zone_files() -> list[str]:
    names: list[str] = list(ZONE_INTERFACES.keys())
    d = settings.dnsmasq_etc_dir
    if os.path.isdir(d):
        for fn in os.listdir(d):
            if not fn.endswith(".conf"):
                continue
            name = fn[:-5]
            if name in ("00-global", RESERVATIONS_FILE[:-5]):
                continue
            conf = _parse_dnsmasq_conf(os.path.join(d, fn))
            if conf["raw"].get("interface") and name not in names:
                names.append(name)
    return names


def list_zones() -> list[dict[str, Any]]:
    return [_zone_from_conf(name, _zone_path(name)) for name in _discover_zone_files()]


def get_zone(name: str) -> dict[str, Any] | None:
    if not ZONE_NAME_RE.match(name):
        return None
    path = _zone_path(name)
    if not os.path.isfile(path):
        return None
    return _zone_from_conf(name, path)


def _render_zone(z: dict[str, Any]) -> str:
    lines = [f"# Mundix360 zone '{z['zone']}' - managed by dashboard"]
    lines.append(f"interface={z['interface']}")
    lines.append("bind-interfaces")
    if z.get("listen_address"):
        lines.append(f"listen-address={z['listen_address']}")
    if z.get("dhcp_start") and z.get("dhcp_end"):
        netmask = z.get("netmask") or "255.255.255.0"
        lease = z.get("lease_time") or "24h"
        lines.append(f"dhcp-range={z['dhcp_start']},{z['dhcp_end']},{netmask},{lease}")
    if z.get("gateway"):
        lines.append(f"dhcp-option=3,{z['gateway']}")
    if z.get("listen_address"):
        lines.append(f"dhcp-option=6,{z['listen_address']}")
    if z.get("domain"):
        lines.append(f"domain={z['domain']}")
        lines.append(f"local=/{z['domain']}/")
    lines.append("expand-hosts")
    for srv in z.get("upstream_dns") or []:
        lines.append(f"server={srv}")
    return "\n".join(lines) + "\n"


def _validate_zone(z: dict[str, Any]) -> None:
    if not ZONE_NAME_RE.match(z.get("zone", "")):
        raise ValueError("invalid zone name (use a-z, 0-9, -, _)")
    if not z.get("interface") or not re.match(r"^[a-z0-9.@_-]{1,15}$", z["interface"]):
        raise ValueError("invalid interface")
    for field in ("listen_address", "gateway", "dhcp_start", "dhcp_end"):
        if z.get(field):
            try:
                ipaddress.ip_address(z[field])
            except ValueError:
                raise ValueError(f"invalid IP in {field}: {z[field]}")
    for srv in z.get("upstream_dns") or []:
        try:
            ipaddress.ip_address(srv)
        except ValueError:
            raise ValueError(f"invalid upstream DNS: {srv}")


def save_zone(z: dict[str, Any], *, create: bool) -> dict[str, Any]:
    _validate_zone(z)
    path = _zone_path(z["zone"])
    if create and os.path.isfile(path):
        raise ValueError(f"zone already exists: {z['zone']}")
    if not create and not os.path.isfile(path):
        raise ValueError(f"zone not found: {z['zone']}")
    content = _render_zone(z)
    _atomic_write(path, content)
    reload_result = _validate_and_reload()
    if not reload_result["ok"]:
        # roll back on failed validation to avoid breaking DNS/DHCP
        if create:
            os.remove(path)
        raise ValueError(f"dnsmasq rejected config: {reload_result['error']}")
    return get_zone(z["zone"]) or z


def delete_zone(name: str) -> dict[str, Any]:
    if name in ZONE_INTERFACES:
        raise ValueError("cannot delete a built-in zone")
    if not ZONE_NAME_RE.match(name):
        raise ValueError("invalid zone name")
    path = _zone_path(name)
    if os.path.isfile(path):
        os.remove(path)
    reload = _validate_and_reload()
    return {"ok": reload["ok"], "zone": name}


# ----------------------------------------------------------- reservations ----

_RES_RE = re.compile(r"^dhcp-host=([0-9a-fA-F:]{17}),([^,]+)(?:,([^,]+))?")


def _reservations_path() -> str:
    return os.path.join(settings.dnsmasq_etc_dir, RESERVATIONS_FILE)


def list_reservations() -> list[dict[str, Any]]:
    path = _reservations_path()
    out: list[dict[str, Any]] = []
    if not os.path.isfile(path):
        return out
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("dhcp-host="):
                m = _RES_RE.match(line)
                if m:
                    mac, a, b = m.group(1), m.group(2), m.group(3)
                    # format: dhcp-host=MAC,[hostname,]IP
                    if b:
                        hostname, ip = a, b
                    else:
                        hostname, ip = "", a
                    out.append({"id": mac, "mac": mac, "hostname": hostname, "ip": ip})
    return out


def _write_reservations(items: list[dict[str, Any]]) -> None:
    lines = ["# Mundix360 DHCP reservations - managed by dashboard\n"]
    for it in items:
        host = it.get("hostname") or ""
        if host:
            lines.append(f"dhcp-host={it['mac']},{host},{it['ip']}\n")
        else:
            lines.append(f"dhcp-host={it['mac']},{it['ip']}\n")
    _atomic_write(_reservations_path(), "".join(lines))


def _validate_reservation(r: dict[str, Any]) -> None:
    if not re.match(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$", r.get("mac", "")):
        raise ValueError("invalid MAC address")
    try:
        ipaddress.ip_address(r.get("ip", ""))
    except ValueError:
        raise ValueError("invalid IP address")
    if r.get("hostname") and not re.match(r"^[a-zA-Z0-9-]{1,63}$", r["hostname"]):
        raise ValueError("invalid hostname")


def save_reservation(r: dict[str, Any], *, create: bool) -> dict[str, Any]:
    _validate_reservation(r)
    items = list_reservations()
    exists = any(i["mac"].lower() == r["mac"].lower() for i in items)
    if create and exists:
        raise ValueError("reservation for this MAC already exists")
    items = [i for i in items if i["mac"].lower() != r["mac"].lower()]
    items.append({"mac": r["mac"], "hostname": r.get("hostname", ""), "ip": r["ip"]})
    _write_reservations(items)
    reload = _validate_and_reload()
    if not reload["ok"]:
        raise ValueError(f"dnsmasq rejected config: {reload['error']}")
    return {"id": r["mac"], "mac": r["mac"], "hostname": r.get("hostname", ""), "ip": r["ip"]}


def delete_reservation(mac: str) -> dict[str, Any]:
    items = [i for i in list_reservations() if i["mac"].lower() != mac.lower()]
    _write_reservations(items)
    _validate_and_reload()
    return {"ok": True, "mac": mac}


# ------------------------------------------------------------- utilities ----

def _atomic_write(path: str, content: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(content)
    os.replace(tmp, path)


def _validate_and_reload() -> dict[str, Any]:
    test = shell.run(["dnsmasq", "--test"], timeout=10)
    # dnsmasq --test prints to stderr; returncode 0 means OK
    if not test.ok:
        return {"ok": False, "error": (test.stderr or test.stdout).strip()}
    reload = shell.run(["systemctl", "reload-or-restart", "dnsmasq"], timeout=20)
    return {"ok": reload.ok, "error": reload.stderr.strip()}


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
