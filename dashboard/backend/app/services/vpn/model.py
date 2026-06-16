"""VPN configuration model (persisted JSON) and validation.

The whole VPN subsystem is OFF by default and isolated: when nothing is
enabled this module touches no live state. The model lives at
``/etc/mundix/vpn.json`` (0600 — it holds private keys) and is the single
source of truth for every VPN role the appliance plays:

  * ``wireguard`` — the appliance as a WireGuard **server/concentrator**
    (road-warrior peers and site-to-site peers).
  * ``openvpn``  — OpenVPN **server** (remote-access + site-to-site).
  * ``fortinet`` — openfortivpn **client** dialling a remote FortiGate SSL-VPN
    (the appliance is the client; LAN reaches the remote subnets through it).
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
from typing import Any

MODEL_PATH = "/etc/mundix/vpn.json"

# WireGuard interface names we manage (wg0, wg1, ...). Kept deliberately tight
# so a value can be interpolated into an nft rule / systemd unit name safely.
_WG_IFACE_RE = re.compile(r"^wg[0-9]{1,3}$")
# OpenVPN tun device names (tun0, tun1, ...).
_TUN_IFACE_RE = re.compile(r"^tun[0-9]{1,3}$")
# pppd interface name pinned for the Fortinet client tunnel (e.g. ppp-forti).
_PPP_IFACE_RE = re.compile(r"^[A-Za-z0-9_-]{1,15}$")
# Pinned tun device for an OpenVPN *client* dial-out connection (ovpnc0..ovpnc999)
# — kept distinct from the OpenVPN server's tun0 and safe to interpolate.
_OVPNC_IFACE_RE = re.compile(r"^ovpnc[0-9]{1,3}$")
# A sha256 certificate digest (hex), used to pin the FortiGate certificate.
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
# A gateway host: IPv4/IPv6 literal or DNS hostname.
_HOST_RE = re.compile(r"^[A-Za-z0-9._:-]{1,253}$")
# Opaque base64 WireGuard keys are exactly 44 chars ending in '='.
_WG_KEY_RE = re.compile(r"^[A-Za-z0-9+/]{43}=$")
_NAME_RE = re.compile(r"^[A-Za-z0-9 ._-]{1,40}$")


# ----------------------------------------------------------------- defaults ---

def _default_wireguard() -> dict[str, Any]:
    return {
        "enabled": False,
        "interface": "wg0",
        "listen_port": 51820,
        "address": "10.20.0.1/24",   # server tunnel address (CIDR)
        "private_key": "",            # generated on first enable
        "public_key": "",
        "dns": "",                    # pushed to road-warrior clients (optional)
        "endpoint_host": "",          # public host clients dial; auto = WAN IP
        "mtu": 1420,
        "peers": [],
    }


def _default_model() -> dict[str, Any]:
    return {
        "wireguard": _default_wireguard(),
        "openvpn": _default_openvpn(),
        "fortinet": _default_fortinet(),
        "ovpn_clients": [],
    }


def _default_fortinet() -> dict[str, Any]:
    return {
        "enabled": False,
        "gateway_host": "",
        "gateway_port": 443,
        "username": "",
        "password": "",              # secret
        "realm": "",
        "trusted_cert": "",          # sha256 hex digest — pins the FortiGate cert (TOFU)
        "iface": "ppp-forti",        # pinned pppd interface name (deterministic firewall)
        "remote_subnets": [],        # subnets reachable through the tunnel (LAN routing/NAT)
        "set_dns": False,            # don't let the remote clobber appliance DNS by default
        "persistent": True,          # auto-reconnect loop
    }


def _norm_fortinet(f: dict[str, Any]) -> dict[str, Any]:
    base = _default_fortinet()
    base.update({k: f[k] for k in base if k in f and k != "remote_subnets"})
    base["enabled"] = bool(f.get("enabled", False))
    base["gateway_host"] = (f.get("gateway_host") or "").strip()
    base["gateway_port"] = int(f.get("gateway_port") or 443)
    base["username"] = (f.get("username") or "").strip()
    base["password"] = f.get("password") or ""
    base["realm"] = (f.get("realm") or "").strip()
    base["trusted_cert"] = (f.get("trusted_cert") or "").strip().lower().replace(":", "")
    base["iface"] = (f.get("iface") or "ppp-forti").strip()
    base["set_dns"] = bool(f.get("set_dns", False))
    base["persistent"] = bool(f.get("persistent", True))
    base["remote_subnets"] = [
        s.strip() for s in (f.get("remote_subnets") or []) if s and s.strip()]
    return base


# ---------------------------------------------------- openvpn client (dial-out)
# The appliance is the *client*: it imports a remote server's `.ovpn` profile and
# dials out (typical to reach a head-office / cloud OpenVPN server). Optionally it
# NATs the LAN through the tunnel and the operator scopes which remote subnets are
# reachable and which are blocked. Mirrors the Fortinet client model.

def _norm_ovpn_client(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": c.get("id") or os.urandom(6).hex(),
        "name": (c.get("name") or "conexao").strip(),
        "description": (c.get("description") or "").strip(),
        "enabled": bool(c.get("enabled", False)),
        "config": c.get("config") or "",            # raw imported .ovpn (may hold keys)
        "username": (c.get("username") or "").strip(),
        "password": c.get("password") or "",        # secret
        "dev": (c.get("dev") or "").strip(),         # pinned tun name; auto-assigned
        "route_lan": bool(c.get("route_lan", False)),
        "remote_subnets": [s.strip() for s in (c.get("remote_subnets") or []) if s and s.strip()],
        "block_subnets": [s.strip() for s in (c.get("block_subnets") or []) if s and s.strip()],
        "accept_pushed_routes": bool(c.get("accept_pushed_routes", True)),
    }


def ovpn_requires_auth(config: str) -> bool:
    """True if the imported profile expects an interactive username/password.

    We treat a bare ``auth-user-pass`` directive (no file argument) as requiring
    credentials, so the dial-out never blocks on a prompt under systemd.
    """
    for raw in (config or "").splitlines():
        line = raw.strip()
        if line.startswith("auth-user-pass"):
            rest = line[len("auth-user-pass"):].strip()
            if not rest:
                return True
    return False



def _default_openvpn() -> dict[str, Any]:
    return {
        "enabled": False,
        "proto": "udp",
        "port": 1194,
        "subnet": "10.21.0.0/24",
        "dev": "tun0",
        "dns": "",
        "full_tunnel": True,
        "endpoint_host": "",          # public host clients dial; auto = WAN IP
        "clients": [],
    }


def _norm_client(c: dict[str, Any]) -> dict[str, Any]:
    ctype = c.get("type") if c.get("type") in ("roadwarrior", "site") else "roadwarrior"
    return {
        "id": c.get("id") or os.urandom(6).hex(),
        "name": (c.get("name") or "client").strip(),
        "cn": (c.get("cn") or "").strip(),
        "type": ctype,
        "enabled": bool(c.get("enabled", True)),
        "site_subnets": [s.strip() for s in (c.get("site_subnets") or []) if s and s.strip()],
        # Site-to-site only: which of OUR networks this remote site may reach.
        # Pushed to the site peer as routes via the CCD. Empty = auto (LAN zones).
        "local_networks": [s.strip() for s in (c.get("local_networks") or []) if s and s.strip()],
        "description": (c.get("description") or "").strip(),
    }


def _norm_openvpn(o: dict[str, Any]) -> dict[str, Any]:
    base = _default_openvpn()
    base.update({k: o[k] for k in base if k in o and k != "clients"})
    base["enabled"] = bool(o.get("enabled", False))
    base["proto"] = o.get("proto") if o.get("proto") in ("udp", "tcp") else "udp"
    base["port"] = int(o.get("port") or 1194)
    base["dev"] = (o.get("dev") or "tun0").strip()
    base["full_tunnel"] = bool(o.get("full_tunnel", True))
    base["clients"] = [_norm_client(c) for c in o.get("clients", [])]
    return base


# --------------------------------------------------------------- normalise ----

def _norm_peer(p: dict[str, Any]) -> dict[str, Any]:
    ptype = p.get("type") if p.get("type") in ("roadwarrior", "site") else "roadwarrior"
    return {
        "id": p.get("id") or os.urandom(6).hex(),
        "name": (p.get("name") or "peer").strip(),
        "type": ptype,
        "enabled": bool(p.get("enabled", True)),
        "address": (p.get("address") or "").strip(),          # tunnel IP, e.g. 10.20.0.2/32
        "public_key": (p.get("public_key") or "").strip(),
        "private_key": (p.get("private_key") or "").strip(),  # only if server-generated
        "preshared_key": (p.get("preshared_key") or "").strip(),
        "site_subnets": [s.strip() for s in (p.get("site_subnets") or []) if s and s.strip()],
        "endpoint": (p.get("endpoint") or "").strip(),        # site peers the box dials (host:port)
        "keepalive": int(p.get("keepalive") or 25),
        "full_tunnel": bool(p.get("full_tunnel", True)),      # road-warrior default route
    }


def _norm_wireguard(w: dict[str, Any]) -> dict[str, Any]:
    base = _default_wireguard()
    base.update({k: w[k] for k in base if k in w and k != "peers"})
    base["enabled"] = bool(w.get("enabled", False))
    base["listen_port"] = int(w.get("listen_port") or 51820)
    base["mtu"] = int(w.get("mtu") or 1420)
    base["interface"] = (w.get("interface") or "wg0").strip()
    base["peers"] = [_norm_peer(p) for p in w.get("peers", [])]
    return base


# -------------------------------------------------------------- load/save -----

def load_model() -> dict[str, Any]:
    try:
        with open(MODEL_PATH) as f:
            m = json.load(f)
    except (OSError, ValueError):
        return _default_model()
    return {
        "wireguard": _norm_wireguard(m.get("wireguard", {})),
        "openvpn": _norm_openvpn(m.get("openvpn", {})),
        "fortinet": _norm_fortinet(m.get("fortinet", {})),
        "ovpn_clients": [_norm_ovpn_client(c) for c in m.get("ovpn_clients", [])],
    }


def save_model(model: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    tmp = MODEL_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(model, f, indent=2)
    os.chmod(tmp, 0o600)            # secrets: private/preshared keys
    os.replace(tmp, MODEL_PATH)


# -------------------------------------------------------------- validation ----

def v_iface(name: str) -> str:
    if not _WG_IFACE_RE.match(name or ""):
        raise ValueError(f"interface WireGuard inválida (use wg0..wg999): {name!r}")
    return name


def v_tun(name: str) -> str:
    if not _TUN_IFACE_RE.match(name or ""):
        raise ValueError(f"dispositivo tun inválido (use tun0..tun999): {name!r}")
    return name


def v_ppp_iface(name: str) -> str:
    if not _PPP_IFACE_RE.match(name or ""):
        raise ValueError(
            f"nome de interface inválido (até 15 caracteres alfanuméricos): {name!r}")
    return name


def v_key(key: str, label: str) -> str:
    if not _WG_KEY_RE.match(key or ""):
        raise ValueError(f"{label} inválida")
    return key


def _v_cidr(value: str, label: str, host: bool = False) -> str:
    try:
        if host:
            ipaddress.ip_interface(value)
        else:
            ipaddress.ip_network(value, strict=False)
    except ValueError:
        raise ValueError(f"{label} inválido: {value!r}")
    return value


def validate_wireguard(w: dict[str, Any]) -> None:
    v_iface(w["interface"])
    if not (1 <= int(w["listen_port"]) <= 65535):
        raise ValueError("porta de escuta deve estar entre 1 e 65535")
    if not (1280 <= int(w["mtu"]) <= 1500):
        raise ValueError("MTU deve estar entre 1280 e 1500")
    _v_cidr(w["address"], "endereço do servidor", host=True)
    if w.get("dns"):
        for d in re.split(r"[,\s]+", w["dns"].strip()):
            if d:
                try:
                    ipaddress.ip_address(d)
                except ValueError:
                    raise ValueError(f"DNS inválido: {d!r}")
    server_net = ipaddress.ip_interface(w["address"]).network
    seen_ips: set[str] = set()
    seen_pub: set[str] = set()
    for p in w["peers"]:
        if not _NAME_RE.match(p["name"]):
            raise ValueError(f"nome de peer inválido: {p['name']!r}")
        if p["public_key"]:
            v_key(p["public_key"], "chave pública do peer")
            if p["public_key"] in seen_pub:
                raise ValueError(f"chave pública duplicada no peer '{p['name']}'")
            seen_pub.add(p["public_key"])
        if p["preshared_key"]:
            v_key(p["preshared_key"], "chave pré-compartilhada")
        if p["address"]:
            _v_cidr(p["address"], f"endereço do peer '{p['name']}'", host=True)
            addr = ipaddress.ip_interface(p["address"]).ip
            if addr not in server_net:
                raise ValueError(
                    f"endereço do peer '{p['name']}' fora da rede do servidor {server_net}")
            if str(addr) in seen_ips:
                raise ValueError(f"endereço {addr} duplicado entre peers")
            seen_ips.add(str(addr))
        for s in p["site_subnets"]:
            _v_cidr(s, f"sub-rede do site '{p['name']}'")
        if p["type"] == "site" and not p["site_subnets"]:
            raise ValueError(f"peer site '{p['name']}' exige ao menos uma sub-rede remota")
    if w["enabled"]:
        enabled_peers = [p for p in w["peers"] if p["enabled"]]
        for p in enabled_peers:
            if not p["public_key"]:
                raise ValueError(f"peer '{p['name']}' sem chave pública")
            if not p["address"]:
                raise ValueError(f"peer '{p['name']}' sem endereço de túnel")


def validate_openvpn(o: dict[str, Any]) -> None:
    v_tun(o["dev"])
    if o["proto"] not in ("udp", "tcp"):
        raise ValueError("protocolo deve ser 'udp' ou 'tcp'")
    if not (1 <= int(o["port"]) <= 65535):
        raise ValueError("porta deve estar entre 1 e 65535")
    _v_cidr(o["subnet"], "rede do servidor OpenVPN")
    if o.get("dns"):
        for d in re.split(r"[,\s]+", o["dns"].strip()):
            if d:
                try:
                    ipaddress.ip_address(d)
                except ValueError:
                    raise ValueError(f"DNS inválido: {d!r}")
    seen_cn: set[str] = set()
    for c in o["clients"]:
        if not _NAME_RE.match(c["name"]):
            raise ValueError(f"nome de cliente inválido: {c['name']!r}")
        if c["cn"] and c["cn"] in seen_cn:
            raise ValueError(f"CN duplicado: {c['cn']}")
        if c["cn"]:
            seen_cn.add(c["cn"])
        for s in c["site_subnets"]:
            _v_cidr(s, f"sub-rede do site '{c['name']}'")
        for s in c["local_networks"]:
            _v_cidr(s, f"rede local anunciada de '{c['name']}'")
        if c["type"] == "site" and not c["site_subnets"]:
            raise ValueError(f"cliente site '{c['name']}' exige ao menos uma sub-rede remota")


def validate_fortinet(f: dict[str, Any]) -> None:
    v_ppp_iface(f["iface"])
    if not (1 <= int(f["gateway_port"]) <= 65535):
        raise ValueError("porta do gateway deve estar entre 1 e 65535")
    if f["gateway_host"] and not _HOST_RE.match(f["gateway_host"]):
        raise ValueError(f"host do gateway inválido: {f['gateway_host']!r}")
    if f["trusted_cert"] and not _SHA256_HEX_RE.match(f["trusted_cert"]):
        raise ValueError("impressão digital do certificado inválida (esperado sha256 hex)")
    for s in f["remote_subnets"]:
        _v_cidr(s, "sub-rede remota")
    if f["enabled"]:
        if not f["gateway_host"]:
            raise ValueError("informe o host do gateway FortiGate")
        if not f["username"]:
            raise ValueError("informe o usuário da VPN")
        if not f["password"]:
            raise ValueError("informe a senha da VPN")


def v_ovpnc(name: str) -> str:
    if not _OVPNC_IFACE_RE.match(name or ""):
        raise ValueError(f"dispositivo do cliente OpenVPN inválido (ovpnc0..ovpnc999): {name!r}")
    return name


def validate_ovpn_client(c: dict[str, Any]) -> None:
    if not _NAME_RE.match(c["name"]):
        raise ValueError(f"nome da conexão inválido: {c['name']!r}")
    if c.get("dev"):
        v_ovpnc(c["dev"])
    for s in c["remote_subnets"]:
        _v_cidr(s, "sub-rede remota acessível")
    for s in c["block_subnets"]:
        _v_cidr(s, "sub-rede bloqueada")
    if c["enabled"]:
        if not (c.get("config") or "").strip():
            raise ValueError("importe o conteúdo do arquivo .ovpn")
        if "remote " not in c["config"] and "remote\t" not in c["config"]:
            raise ValueError("o perfil .ovpn não contém uma linha 'remote <host> <porta>'")
        if ovpn_requires_auth(c["config"]) and not (c.get("username") and c.get("password")):
            raise ValueError("este perfil exige usuário e senha (auth-user-pass)")
