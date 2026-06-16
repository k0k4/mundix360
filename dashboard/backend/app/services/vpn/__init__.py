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
from . import fortinet as _ft
from . import ovpnclient as _ovc


# Aggregated nft fragment helpers consumed by fwmanage.render() — every enabled
# VPN role contributes its firewall openings (WireGuard + OpenVPN server +
# Fortinet client + OpenVPN client dial-out).
def nft_input_accepts(wan: str | None = None) -> list[str]:
    return (_wg.nft_input_accepts(wan) + _ov.nft_input_accepts(wan)
            + _ft.nft_input_accepts(wan) + _ovc.nft_input_accepts(wan))


def nft_forward_accepts(wan: str | None = None) -> list[str]:
    return (_wg.nft_forward_accepts(wan) + _ov.nft_forward_accepts(wan)
            + _ft.nft_forward_accepts(wan) + _ovc.nft_forward_accepts(wan))


def nft_postrouting_masq(wan: str | None = None) -> list[str]:
    return (_wg.nft_postrouting_masq(wan) + _ov.nft_postrouting_masq(wan)
            + _ft.nft_postrouting_masq(wan) + _ovc.nft_postrouting_masq(wan))


_lock = threading.RLock()

_SERVER_FIELDS = (
    "enabled", "interface", "listen_port", "address", "dns", "endpoint_host", "mtu")


# ---------------------------------------------------------------- status ------

def get_status() -> dict[str, Any]:
    return {"wireguard": _wg.status(), "openvpn": _ov.status(),
            "fortinet": _ft.status(), "ovpn_clients": _ovc.status()}


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
            "local_networks": client["local_networks"],
            "description": client["description"],
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
    with _lock:
        model = _m.load_model()
        ov = model["openvpn"]
        client = next((c for c in ov["clients"] if c["id"] == client_id), None)
        if not client:
            raise ValueError("cliente não encontrado")
        # A client profile only needs the PKI (CA + server + client certs +
        # tls-crypt key) and a reachable endpoint — the server unit does not have
        # to be running to hand out a .ovpn. Build the PKI/cert on demand so
        # pre-provisioning works even before the operator clicks "Aplicar".
        _ov.ensure_pki()
        _ov.build_client(client["cn"])
        return _ov.client_ovpn(ov, client)


# ----------------------------------------------- OpenVPN client (dial-out) ----
# The appliance imports a remote server's .ovpn and dials out. Multiple
# independent connections are supported, each pinned to its own tun device.

def _assign_ovpnc_dev(clients: list[dict[str, Any]], client: dict[str, Any]) -> str:
    if client.get("dev"):
        return client["dev"]
    taken = {c.get("dev") for c in clients if c["id"] != client["id"]}
    for i in range(1000):
        cand = f"ovpnc{i}"
        if cand not in taken:
            return cand
    raise ValueError("sem dispositivo tun livre para o cliente OpenVPN")


def save_ovpn_client(data: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        model = _m.load_model()
        clients = model["ovpn_clients"]
        client = _m._norm_ovpn_client(data)
        existing = next((c for c in clients if c["id"] == client["id"]), None)
        if existing and not client.get("config"):
            client["config"] = existing["config"]      # keep imported profile
        if existing and not data.get("password") and not client.get("password"):
            client["password"] = existing.get("password", "")  # keep stored secret
        if existing and not client.get("dev"):
            client["dev"] = existing["dev"]             # keep the pinned device
        client["dev"] = _assign_ovpnc_dev(clients, client)
        client = _m._norm_ovpn_client(client)
        _m.validate_ovpn_client(client)
        # Stop any previous instance whose device changed, to avoid a stale tun.
        if existing and existing.get("enabled") and existing.get("dev") != client["dev"]:
            try:
                _ovc.teardown(existing)
            except Exception:
                pass
        model["ovpn_clients"] = [c for c in clients if c["id"] != client["id"]] + [client]
        _m.save_model(model)
        result = _ovc.apply_client(client)
        st = _ovc._client_status(client)
        st["applied"] = result["applied"]
        st["detail"] = result["detail"]
        return st


def delete_ovpn_client(client_id: str) -> dict[str, Any]:
    with _lock:
        model = _m.load_model()
        clients = model["ovpn_clients"]
        client = next((c for c in clients if c["id"] == client_id), None)
        if not client:
            raise ValueError("conexão não encontrada")
        try:
            _ovc.teardown(client)
        except Exception:
            pass
        model["ovpn_clients"] = [c for c in clients if c["id"] != client_id]
        _m.save_model(model)
        return {"deleted": client_id}


def ovpn_client_rendered(client_id: str) -> str:
    """Return the effective rendered config (secrets redacted) for inspection."""
    with _lock:
        model = _m.load_model()
        client = next((c for c in model["ovpn_clients"] if c["id"] == client_id), None)
        if not client:
            raise ValueError("conexão não encontrada")
        return _ovc.render_config(client)


def ovpn_client_logs(client_id: str, lines: int = 200) -> dict[str, Any]:
    """Live journal of a dial-out connection's systemd unit (for the log viewer)."""
    return _ovc.client_logs(client_id, lines)


def reapply_ovpn_clients() -> None:
    """Re-assert every enabled dial-out connection (used on startup/reconcile)."""
    with _lock:
        for c in _m.load_model()["ovpn_clients"]:
            if c.get("enabled"):
                try:
                    _ovc.apply_client(c)
                except Exception:
                    pass


# ---------------------------------------------------------- Fortinet client ---

_FT_FIELDS = (
    "enabled", "gateway_host", "gateway_port", "username", "password", "realm",
    "trusted_cert", "iface", "remote_subnets", "set_dns", "persistent")


def set_fortinet(data: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        model = _m.load_model()
        ft = model["fortinet"]
        for k in _FT_FIELDS:
            if k in data and data[k] is not None:
                ft[k] = data[k]
        # Preserve the stored password when the client doesn't resend it.
        if not (data.get("password") or "").strip():
            ft["password"] = model["fortinet"].get("password", "")
        ft = _m._norm_fortinet(ft)
        model["fortinet"] = ft
        _m.validate_fortinet(ft)
        _m.save_model(model)
        _ft.apply_client(ft)
        return _ft.status()


def fortinet_probe_cert(host: str | None = None, port: int | None = None) -> dict[str, Any]:
    ft = _m.load_model()["fortinet"]
    h = (host or ft.get("gateway_host") or "").strip()
    p = int(port or ft.get("gateway_port") or 443)
    return _ft.probe_certificate(h, p)
