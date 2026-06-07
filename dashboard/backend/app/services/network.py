"""Network/VLAN/DHCP management derived from dnsmasq zone configs.

Reads and writes live dnsmasq config files under /etc/dnsmasq.d. Mutations are
validated with `dnsmasq --test` before reloading the service.
"""
from __future__ import annotations

import ipaddress
import os
import re
import threading
import time
from typing import Any

from ..config import settings
from . import shell

# Serialises all dnsmasq config mutations (write → validate → restart → rollback)
# so concurrent requests can't interleave and corrupt the merged config state.
# Shared with services/dns.py (imported from here).
config_lock = threading.RLock()

# Static description of zones <-> interfaces (matches nftables.conf / dnsmasq).
ZONE_INTERFACES = {
    "lan": {"iface": "ens19", "net": "192.168.0.0/24"},
    "dmz": {"iface": "ens20", "net": "10.0.0.0/8"},
    "iot": {"iface": "ens21", "net": "172.16.0.0/16"},
}

RESERVATIONS_FILE = "mundix-dhcp-reservations.conf"
ZONE_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,30}$")


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


def _derive_network(ip: str | None, netmask: str | None) -> str | None:
    if not ip or not netmask:
        return None
    try:
        return str(ipaddress.ip_network(f"{ip}/{netmask}", strict=False))
    except ValueError:
        return None


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
    listen_address = conf["raw"].get("listen-address")
    # Prefer the real subnet derived from the live config; fall back to the
    # static interface map only when we can't compute it.
    network = _derive_network(listen_address or gateway, netmask) or meta.get("net")
    return {
        "zone": name,
        "id": name,
        "interface": conf["raw"].get("interface") or meta.get("iface"),
        "network": network,
        "listen_address": listen_address,
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

    # Subnet coherence: the appliance IP, gateway and DHCP pool must all live in
    # the same network defined by listen_address/gateway + netmask.
    netmask = z.get("netmask")
    ref_ip = z.get("listen_address") or z.get("gateway")
    net = None
    if netmask:
        try:
            net = ipaddress.ip_network(f"{ref_ip or '0.0.0.0'}/{netmask}", strict=False)
        except ValueError:
            raise ValueError(f"máscara de rede inválida: {netmask}")
    if net and ref_ip:
        for field in ("listen_address", "gateway", "dhcp_start", "dhcp_end"):
            v = z.get(field)
            if v and ipaddress.ip_address(v) not in net:
                raise ValueError(f"{field} ({v}) está fora da sub-rede {net}")
    start, end = z.get("dhcp_start"), z.get("dhcp_end")
    if start and end and int(ipaddress.ip_address(start)) > int(ipaddress.ip_address(end)):
        raise ValueError("pool DHCP inválido: início é maior que o fim")
    if bool(start) != bool(end):
        raise ValueError("informe início e fim do pool DHCP (ou nenhum)")


def save_zone(z: dict[str, Any], *, create: bool) -> dict[str, Any]:
    _validate_zone(z)
    with config_lock:
        path = _zone_path(z["zone"])
        if create and os.path.isfile(path):
            raise ValueError(f"zone already exists: {z['zone']}")
        if not create and not os.path.isfile(path):
            raise ValueError(f"zone not found: {z['zone']}")
        prev = None
        if os.path.isfile(path):
            with open(path) as f:
                prev = f.read()
        content = _render_zone(z)
        _atomic_write(path, content)
        reload_result = _validate_and_reload()
        if not reload_result["ok"]:
            # roll back on failed validation to avoid breaking DNS/DHCP
            if create:
                os.remove(path)
            elif prev is not None:
                _atomic_write(path, prev)
            _validate_and_reload()
            raise ValueError(f"dnsmasq rejected config: {reload_result['error']}")
    return get_zone(z["zone"]) or z


def delete_zone(name: str) -> dict[str, Any]:
    if name in ZONE_INTERFACES:
        raise ValueError("cannot delete a built-in zone")
    if not ZONE_NAME_RE.match(name):
        raise ValueError("invalid zone name")
    with config_lock:
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
    with config_lock:
        items = list_reservations()
        exists = any(i["mac"].lower() == r["mac"].lower() for i in items)
        if create and exists:
            raise ValueError("reservation for this MAC already exists")
        prev = items
        items = [i for i in items if i["mac"].lower() != r["mac"].lower()]
        items.append({"mac": r["mac"], "hostname": r.get("hostname", ""), "ip": r["ip"]})
        _write_reservations(items)
        reload = _validate_and_reload()
        if not reload["ok"]:
            _write_reservations(prev)
            _validate_and_reload()
            raise ValueError(f"dnsmasq rejected config: {reload['error']}")
    return {"id": r["mac"], "mac": r["mac"], "hostname": r.get("hostname", ""), "ip": r["ip"]}


def delete_reservation(mac: str) -> dict[str, Any]:
    with config_lock:
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
    # NOTE: dnsmasq's ExecReload is SIGHUP, which only re-reads /etc/hosts and
    # clears the cache — it does NOT re-read /etc/dnsmasq.d/*.conf. Config-file
    # mutations (zones, reservations, records, resolvers) therefore require a
    # full restart to actually take effect.
    reload = shell.run(["systemctl", "restart", "dnsmasq"], timeout=30)
    return {"ok": reload.ok, "error": reload.stderr.strip()}


_LEASE_RE = re.compile(r"^(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)")


def _neighbors() -> dict[str, dict[str, str]]:
    """Map IP -> {state, mac} from the kernel neighbour (ARP/NDP) table.

    Neighbour state is *recently-seen* signal, NOT authoritative presence:
    REACHABLE/DELAY/PROBE/STALE => seen recently, FAILED/INCOMPLETE => no answer,
    absent => unknown.
    """
    out: dict[str, dict[str, str]] = {}
    res = shell.run(["ip", "neigh", "show"], timeout=8)
    if not res.ok:
        return out
    for line in res.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        ip = parts[0]
        mac = ""
        if "lladdr" in parts:
            try:
                mac = parts[parts.index("lladdr") + 1]
            except IndexError:
                mac = ""
        # last token is the neighbour state (REACHABLE, STALE, FAILED, …)
        state = parts[-1]
        out[ip] = {"state": state, "mac": mac}
    return out


_SEEN_STATES = {"REACHABLE", "DELAY", "PROBE", "STALE", "PERMANENT", "NOARP"}
_DOWN_STATES = {"FAILED", "INCOMPLETE"}


def _presence(state: str | None) -> str:
    if not state:
        return "unknown"
    s = state.upper()
    if s in _SEEN_STATES:
        return "seen"
    if s in _DOWN_STATES:
        return "down"
    return "unknown"


def dhcp_leases() -> list[dict[str, Any]]:
    leases: list[dict[str, Any]] = []
    path = settings.dhcp_leases_file
    if not os.path.isfile(path):
        return leases
    neigh = _neighbors()
    reserved_macs = {i["mac"].lower() for i in list_reservations()}
    with open(path) as f:
        for line in f:
            m = _LEASE_RE.match(line.strip())
            if not m:
                continue
            expiry, mac, ip, hostname, client_id = m.groups()
            zone = _zone_for_ip(ip)
            n = neigh.get(ip, {})
            # Strong match only when the neighbour MAC agrees with the lease MAC.
            n_state = n.get("state") if (not n.get("mac") or n.get("mac", "").lower() == mac.lower()) else None
            leases.append({
                "expiry": int(expiry),
                "mac": mac,
                "ip": ip,
                "hostname": None if hostname == "*" else hostname,
                "client_id": None if client_id == "*" else client_id,
                "zone": zone,
                "neighbor_state": n_state,
                "presence": _presence(n_state),
                "is_reserved": mac.lower() in reserved_macs,
            })
    return leases


def reserve_lease(mac: str) -> dict[str, Any]:
    """Promote an active lease to a static reservation (reuses save_reservation)."""
    lease = next((l for l in dhcp_leases() if l["mac"].lower() == mac.lower()), None)
    if not lease:
        raise ValueError("lease not found")
    return save_reservation(
        {"mac": lease["mac"], "ip": lease["ip"], "hostname": lease.get("hostname") or ""},
        create=True,
    )


def _ip_int(ip: str) -> int | None:
    try:
        a = ipaddress.ip_address(ip)
        return int(a) if a.version == 4 else None
    except ValueError:
        return None


def dhcp_pools() -> list[dict[str, Any]]:
    """Per-zone DHCP pool utilisation. Only simple IPv4 dhcp-range start,end
    forms are supported; anything else is reported as unsupported."""
    now = time.time()
    leases = dhcp_leases()
    pools: list[dict[str, Any]] = []
    for z in list_zones():
        start, end = z.get("dhcp_start"), z.get("dhcp_end")
        si, ei = (_ip_int(start) if start else None), (_ip_int(end) if end else None)
        if si is None or ei is None or ei < si:
            pools.append({
                "zone": z["zone"], "interface": z.get("interface"),
                "dhcp_start": start, "dhcp_end": end,
                "supported": bool(start or end), "pool_size": None,
                "active": None, "utilization": None,
            })
            continue
        size = ei - si + 1
        active = 0
        for l in leases:
            li = _ip_int(l["ip"])
            if li is None or not (si <= li <= ei):
                continue
            if l["expiry"] and l["expiry"] < now:  # expired
                continue
            active += 1
        pools.append({
            "zone": z["zone"], "interface": z.get("interface"),
            "dhcp_start": start, "dhcp_end": end, "supported": True,
            "pool_size": size, "active": active,
            "utilization": round(active / size * 100, 1) if size else 0.0,
        })
    return pools


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
