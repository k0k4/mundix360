"""VPN configuration model (persisted JSON) and validation.

The whole VPN subsystem is OFF by default and isolated: when nothing is
enabled this module touches no live state. The model lives at
``/etc/mundix/vpn.json`` (0600 — it holds private keys) and is the single
source of truth for every VPN role the appliance plays:

  * ``wireguard`` — the appliance as a WireGuard **server/concentrator**
    (road-warrior peers and site-to-site peers).
  * (future) ``openvpn``  — OpenVPN server.
  * (future) ``fortinet`` — openfortivpn **client** dialling a remote FortiGate.

Only the ``wireguard`` section is implemented in this phase; the others are
reserved so the on-disk schema stays stable across phases.
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
    return {"wireguard": _default_wireguard()}


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
    return {"wireguard": _norm_wireguard(m.get("wireguard", {}))}


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
