"""VPN subsystem public API.

Thin orchestration over the role modules (currently WireGuard server). Routers
call these functions; ``fwmanage.render`` imports this package lazily for the
``nft_*`` firewall fragments. All state changes validate, persist the model and
re-assert the live interface + firewall.
"""
from __future__ import annotations

import ipaddress
import threading
from typing import Any

from . import model as _m
from . import wireguard as _wg
from . import openvpn as _ov


# Aggregated nft fragment helpers consumed by fwmanage.render() — every enabled
# VPN role contributes its firewall openings (WireGuard + OpenVPN).
def nft_input_accepts(wan: str | None = None) -> list[str]:
    return _wg.nft_input_accepts(wan) + _ov.nft_input_accepts(wan)


def nft_forward_accepts(wan: str | None = None) -> list[str]:
    return _wg.nft_forward_accepts(wan) + _ov.nft_forward_accepts(wan)


def nft_postrouting_masq(wan: str | None = None) -> list[str]:
    return _wg.nft_postrouting_masq(wan) + _ov.nft_postrouting_masq(wan)


_lock = threading.RLock()

_SERVER_FIELDS = (
    "enabled", "interface", "listen_port", "address", "dns", "endpoint_host", "mtu")


# ---------------------------------------------------------------- status ------

def get_status() -> dict[str, Any]:
    return {"wireguard": _wg.status(), "openvpn": _ov.status()}


# ------------------------------------------------------- server settings ------

def set_wireguard(data: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        model = _m.load_model()
        wg = model["wireguard"]
        for k in _SERVER_FIELDS:
            if k in data and data[k] is not None:
                wg[k] = data[k]
        wg = _m._norm_wireguard(wg)
        if wg["enabled"]:
            _wg._ensure_server_keys(wg)
        model["wireguard"] = wg
        _m.validate_wireguard(wg)
        _m.save_model(model)
        _wg.apply_interface(wg)
        return _wg.status()


# ---------------------------------------------------------------- peers -------

def _next_free_address(wg: dict[str, Any], exclude_id: str | None = None) -> str:
    net = ipaddress.ip_interface(wg["address"]).network
    server_ip = ipaddress.ip_interface(wg["address"]).ip
    used = {server_ip}
    for p in wg["peers"]:
        if p["id"] == exclude_id or not p.get("address"):
            continue
        try:
            used.add(ipaddress.ip_interface(p["address"]).ip)
        except ValueError:
            pass
    for host in net.hosts():
        if host not in used:
            return f"{host}/32"
    raise ValueError("sem endereços livres na rede do túnel")


def save_peer(data: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        model = _m.load_model()
        wg = model["wireguard"]
        peer = _m._norm_peer(data)

        existing = next((p for p in wg["peers"] if p["id"] == peer["id"]), None)
        if existing:
            # Preserve secrets the client didn't resend.
            peer["private_key"] = peer["private_key"] or existing.get("private_key", "")
            peer["public_key"] = peer["public_key"] or existing.get("public_key", "")
            peer["preshared_key"] = peer["preshared_key"] or existing.get("preshared_key", "")
            peer["address"] = peer["address"] or existing.get("address", "")

        # Key strategy: if no public key supplied, generate a keypair server-side
        # so we can export a ready-to-use client config + QR. A supplied public
        # key (bring-your-own) keeps the private key off the appliance.
        if not peer["public_key"]:
            priv = _wg.gen_private_key()
            peer["private_key"] = priv
            peer["public_key"] = _wg.public_key_of(priv)
        if data.get("preshared_key") is None and not existing:
            peer["preshared_key"] = _wg.gen_preshared_key()

        if not peer["address"]:
            peer["address"] = _next_free_address(wg, exclude_id=peer["id"])

        wg["peers"] = [p for p in wg["peers"] if p["id"] != peer["id"]] + [peer]
        wg = _m._norm_wireguard(wg)
        model["wireguard"] = wg
        _m.validate_wireguard(wg)
        _m.save_model(model)
        if wg["enabled"]:
            _wg.apply_interface(wg)
        return _peer_public(peer)


def delete_peer(peer_id: str) -> dict[str, Any]:
    with _lock:
        model = _m.load_model()
        wg = model["wireguard"]
        before = len(wg["peers"])
        wg["peers"] = [p for p in wg["peers"] if p["id"] != peer_id]
        if len(wg["peers"]) == before:
            raise ValueError("peer não encontrado")
        model["wireguard"] = wg
        _m.save_model(model)
        if wg["enabled"]:
            _wg.apply_interface(wg)
        return {"deleted": peer_id}


def peer_client_config(peer_id: str) -> str:
    wg = _m.load_model()["wireguard"]
    p = next((x for x in wg["peers"] if x["id"] == peer_id), None)
    if not p:
        raise ValueError("peer não encontrado")
    return _wg.render_client_conf(wg, p)


def peer_qr(peer_id: str) -> str:
    return _wg.client_qr_svg(peer_client_config(peer_id))


def _peer_public(p: dict[str, Any]) -> dict[str, Any]:
    """Peer view safe to return over the API (no private/preshared keys)."""
    return {
        "id": p["id"],
        "name": p["name"],
        "type": p["type"],
        "enabled": p["enabled"],
        "address": p["address"],
        "public_key": p["public_key"],
        "has_private_key": bool(p.get("private_key")),
        "site_subnets": p.get("site_subnets", []),
        "endpoint": p.get("endpoint", ""),
        "full_tunnel": p.get("full_tunnel", True),
    }


# ----------------------------------------------------------- OpenVPN server ---

_OVPN_FIELDS = (
    "enabled", "proto", "port", "subnet", "dev", "dns", "full_tunnel", "endpoint_host")


def set_openvpn(data: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        model = _m.load_model()
        ov = model["openvpn"]
        for k in _OVPN_FIELDS:
            if k in data and data[k] is not None:
                ov[k] = data[k]
        ov = _m._norm_openvpn(ov)
        model["openvpn"] = ov
        _m.validate_openvpn(ov)
        _m.save_model(model)
        _ov.apply_server(ov)
        return _ov.status()


def save_client(data: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        model = _m.load_model()
        ov = model["openvpn"]
        client = _m._norm_client(data)
        existing = next((c for c in ov["clients"] if c["id"] == client["id"]), None)
        if existing:
            client["cn"] = existing["cn"]  # CN is immutable once issued
        if not client["cn"]:
            taken = {c["cn"] for c in ov["clients"] if c["cn"]}
            client["cn"] = _ov.cn_for(client["name"], taken)
        ov["clients"] = [c for c in ov["clients"] if c["id"] != client["id"]] + [client]
        ov = _m._norm_openvpn(ov)
        model["openvpn"] = ov
        _m.validate_openvpn(ov)
        _m.save_model(model)
        if ov["enabled"]:
            _ov.apply_server(ov)
        return {
            "id": client["id"], "name": client["name"], "cn": client["cn"],
            "type": client["type"], "enabled": client["enabled"],
            "site_subnets": client["site_subnets"],
        }


def delete_client(client_id: str) -> dict[str, Any]:
    with _lock:
        model = _m.load_model()
        ov = model["openvpn"]
        client = next((c for c in ov["clients"] if c["id"] == client_id), None)
        if not client:
            raise ValueError("cliente não encontrado")
        # Real revocation: the cert is invalidated via the CRL even if the client
        # keeps its key file.
        try:
            _ov.revoke_client(client["cn"])
        except Exception:
            pass
        ov["clients"] = [c for c in ov["clients"] if c["id"] != client_id]
        model["openvpn"] = ov
        _m.save_model(model)
        if ov["enabled"]:
            _ov.apply_server(ov)
        return {"deleted": client_id}


def openvpn_client_config(client_id: str) -> str:
    model = _m.load_model()
    ov = model["openvpn"]
    client = next((c for c in ov["clients"] if c["id"] == client_id), None)
    if not client:
        raise ValueError("cliente não encontrado")
    if not _ov.pki_ready():
        raise ValueError("PKI ainda não inicializada — ative o OpenVPN primeiro")
    _ov.build_client(client["cn"])
    return _ov.client_ovpn(ov, client)
