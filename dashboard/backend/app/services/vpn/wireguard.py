"""WireGuard server/concentrator management.

The appliance acts as a WireGuard server: road-warrior peers (laptops/phones)
and site-to-site peers connect in. This module owns:

  * key material (server keypair, per-peer keys + preshared keys),
  * the on-disk interface config ``/etc/wireguard/<iface>.conf`` (0600),
  * the systemd interface lifecycle via ``wg-quick@<iface>``,
  * live status (handshake/transfer) via ``wg show``,
  * ready-to-use client config + QR export for road-warrior peers,
  * nft rule fragments consumed by fwmanage (input/forward/NAT) so the
    policy-drop firewall actually lets the tunnel through — anti-lockout safe.

NAT/forward/input openings are produced as *data* (``nft_*`` helpers) and merged
by ``fwmanage.render`` so the managed ruleset stays the single source of truth.
"""
from __future__ import annotations

import base64
import ipaddress
import re
from typing import Any

from .. import shell
from . import model as _m

WG_DIR = "/etc/wireguard"


# ------------------------------------------------------------- key helpers ----

def gen_private_key() -> str:
    r = shell.run(["wg", "genkey"], timeout=8)
    if not r.ok or not r.stdout.strip():
        raise RuntimeError("falha ao gerar chave privada WireGuard")
    return r.stdout.strip()


def public_key_of(private_key: str) -> str:
    r = shell.run(["wg", "pubkey"], input_text=private_key.strip() + "\n", timeout=8)
    if not r.ok or not r.stdout.strip():
        raise RuntimeError("falha ao derivar chave pública WireGuard")
    return r.stdout.strip()


def gen_preshared_key() -> str:
    r = shell.run(["wg", "genpsk"], timeout=8)
    if not r.ok or not r.stdout.strip():
        raise RuntimeError("falha ao gerar chave pré-compartilhada")
    return r.stdout.strip()


def _ensure_server_keys(wg: dict[str, Any]) -> None:
    """Generate the server keypair on first enable; always keep public derived
    from the stored private key."""
    if not wg.get("private_key"):
        wg["private_key"] = gen_private_key()
        wg["public_key"] = ""
    if wg["private_key"] and not wg.get("public_key"):
        wg["public_key"] = public_key_of(wg["private_key"])


# ----------------------------------------------------------- live network -----

def _wan_iface() -> str | None:
    try:
        from .. import fwmanage
        wan = fwmanage._wan_iface()
        return wan or None
    except Exception:
        return None


def _wan_ip() -> str | None:
    """Source IP the box uses to reach the Internet — the natural endpoint a
    road-warrior dials when the operator hasn't pinned a public hostname."""
    r = shell.run(["ip", "-o", "route", "get", "1.1.1.1"], timeout=8)
    m = re.search(r"\bsrc\s+(\S+)", r.stdout)
    return m.group(1) if m else None


def effective_endpoint(wg: dict[str, Any]) -> str | None:
    host = (wg.get("endpoint_host") or "").strip() or _wan_ip()
    if not host:
        return None
    return f"{host}:{int(wg['listen_port'])}"


def _lan_subnets() -> list[str]:
    """Internal zone subnets — used for split-tunnel client AllowedIPs."""
    nets: list[str] = []
    try:
        from .. import network
        for z in network.list_zones():
            n = (z.get("network") or "").strip()
            if n:
                try:
                    ipaddress.ip_network(n, strict=False)
                    nets.append(n)
                except ValueError:
                    pass
    except Exception:
        pass
    return nets


# ----------------------------------------------------------- config render ----

def render_server_conf(wg: dict[str, Any]) -> str:
    """Render /etc/wireguard/<iface>.conf for wg-quick. We deliberately keep NAT
    and forwarding OUT of PostUp/PostDown — fwmanage owns those — so wg-quick
    only manages the interface, address and routes."""
    L: list[str] = []
    a = L.append
    a("# AUTO-GERADO pelo Mundix360 — não edite à mão (use o dashboard).")
    a("[Interface]")
    a(f"Address = {wg['address']}")
    a(f"ListenPort = {int(wg['listen_port'])}")
    a(f"PrivateKey = {wg['private_key']}")
    a(f"MTU = {int(wg['mtu'])}")
    for p in wg["peers"]:
        if not p.get("enabled") or not p.get("public_key") or not p.get("address"):
            continue
        a("")
        a(f"[Peer]  # {p['name']}")
        a(f"PublicKey = {p['public_key']}")
        if p.get("preshared_key"):
            a(f"PresharedKey = {p['preshared_key']}")
        allowed = _server_allowed_ips(p)
        a(f"AllowedIPs = {allowed}")
        if p["type"] == "site" and p.get("endpoint"):
            a(f"Endpoint = {p['endpoint']}")
            a(f"PersistentKeepalive = {int(p.get('keepalive') or 25)}")
    return "\n".join(L) + "\n"


def _server_allowed_ips(p: dict[str, Any]) -> str:
    """What the SERVER routes toward this peer: its tunnel IP (as /32) plus, for
    site peers, the remote LANs behind it."""
    host = ipaddress.ip_interface(p["address"]).ip
    parts = [f"{host}/32"]
    if p["type"] == "site":
        parts.extend(p.get("site_subnets") or [])
    return ", ".join(parts)


def render_client_conf(wg: dict[str, Any], p: dict[str, Any]) -> str:
    """Ready-to-import road-warrior config. Requires the peer's private key,
    which only exists when the server generated the keypair."""
    if not p.get("private_key"):
        raise ValueError(
            "este peer foi cadastrado com chave pública externa; o Mundix não "
            "possui a chave privada para exportar a configuração do cliente")
    endpoint = effective_endpoint(wg)
    if not endpoint:
        raise ValueError("endpoint indisponível: defina o host público ou conecte a WAN")
    if p.get("full_tunnel", True):
        allowed = "0.0.0.0/0, ::/0"
    else:
        server_net = str(ipaddress.ip_interface(wg["address"]).network)
        allowed = ", ".join([server_net, *_lan_subnets()])
    L: list[str] = []
    a = L.append
    a("[Interface]")
    a(f"PrivateKey = {p['private_key']}")
    a(f"Address = {p['address']}")
    if wg.get("dns"):
        a(f"DNS = {wg['dns']}")
    a(f"MTU = {int(wg['mtu'])}")
    a("")
    a(f"[Peer]  # {wg.get('public_key', 'server')[:8]}")
    a(f"PublicKey = {wg['public_key']}")
    if p.get("preshared_key"):
        a(f"PresharedKey = {p['preshared_key']}")
    a(f"Endpoint = {endpoint}")
    a(f"AllowedIPs = {allowed}")
    a(f"PersistentKeepalive = {int(p.get('keepalive') or 25)}")
    return "\n".join(L) + "\n"


def client_qr_svg(conf_text: str) -> str:
    """Return an <img>-embeddable data URL (SVG) of the client config QR."""
    r = shell.run(["qrencode", "-t", "SVG", "-o", "-", "-l", "M"],
                  input_text=conf_text, timeout=8)
    if not r.ok or "<svg" not in r.stdout:
        raise RuntimeError("falha ao gerar QR code (qrencode)")
    b64 = base64.b64encode(r.stdout.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


# ------------------------------------------------------------- apply/state ----

def _write_conf(wg: dict[str, Any]) -> str:
    import os
    iface = _m.v_iface(wg["interface"])
    os.makedirs(WG_DIR, exist_ok=True)
    path = f"{WG_DIR}/{iface}.conf"
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(render_server_conf(wg))
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path


def _systemctl(*args: str) -> shell.CommandResult:
    return shell.run(["systemctl", *args], timeout=20)


def apply_interface(wg: dict[str, Any]) -> dict[str, Any]:
    """Bring the WireGuard interface to the desired state and refresh the
    firewall openings. Tears the interface down when disabled."""
    iface = _m.v_iface(wg["interface"])
    unit = f"wg-quick@{iface}"
    if wg.get("enabled"):
        _write_conf(wg)
        _systemctl("enable", unit)
        r = _systemctl("restart", unit)
        ok = r.ok
        detail = "" if ok else (r.stderr.strip() or r.stdout.strip())
    else:
        _systemctl("stop", unit)
        _systemctl("disable", unit)
        ok, detail = True, ""
    _refresh_firewall()
    return {"applied": ok, "detail": detail}


def _refresh_firewall() -> None:
    """Re-render the managed firewall so VPN input/forward/NAT openings track the
    current model (added when enabled, removed when disabled)."""
    try:
        from .. import fwmanage
        fwmanage.reapply()
    except Exception:
        pass


# ------------------------------------------------------------ nft fragments ---
# Consumed by fwmanage.render(). Each returns bare nft rule lines (no
# indentation). They are defensive: any inconsistency yields [] so the firewall
# render never fails because of VPN state.

def nft_input_accepts(wan: str | None = None) -> list[str]:
    try:
        wg = _m.load_model()["wireguard"]
        if not wg["enabled"]:
            return []
        port = int(wg["listen_port"])
        if not (1 <= port <= 65535):
            return []
        return [f"udp dport {port} accept  # mundix-vpn wireguard"]
    except Exception:
        return []


def nft_forward_accepts(wan: str | None = None) -> list[str]:
    try:
        wg = _m.load_model()["wireguard"]
        if not wg["enabled"]:
            return []
        iface = _m.v_iface(wg["interface"])
        return [
            f'iifname "{iface}" accept  # mundix-vpn',
            f'oifname "{iface}" accept  # mundix-vpn',
        ]
    except Exception:
        return []


def nft_postrouting_masq(wan: str | None = None) -> list[str]:
    try:
        wg = _m.load_model()["wireguard"]
        if not wg["enabled"] or not wan:
            return []
        from .. import fwmanage
        wan_if = fwmanage._v_iface(wan)
        net = str(ipaddress.ip_interface(wg["address"]).network)
        return [f'oifname "{wan_if}" ip saddr {net} masquerade  # mundix-vpn']
    except Exception:
        return []


# ---------------------------------------------------------------- status ------

def _wg_show(iface: str) -> dict[str, dict[str, Any]]:
    """Parse `wg show <iface> dump` → {peer_pubkey: {handshake, rx, tx, endpoint}}."""
    out: dict[str, dict[str, Any]] = {}
    r = shell.run(["wg", "show", iface, "dump"], timeout=8)
    if not r.ok:
        return out
    lines = r.stdout.splitlines()
    for line in lines[1:]:  # first line is the interface itself
        f = line.split("\t")
        if len(f) < 8:
            continue
        pub, _psk, endpoint, _allowed, hs, rx, tx, _ka = f[:8]
        out[pub] = {
            "endpoint": endpoint if endpoint != "(none)" else "",
            "last_handshake": int(hs) if hs.isdigit() else 0,
            "rx_bytes": int(rx) if rx.isdigit() else 0,
            "tx_bytes": int(tx) if tx.isdigit() else 0,
        }
    return out


def status() -> dict[str, Any]:
    wg = _m.load_model()["wireguard"]
    iface = wg["interface"]
    live = _wg_show(iface) if wg["enabled"] else {}
    unit_active = False
    if wg["enabled"]:
        unit_active = _systemctl("is-active", f"wg-quick@{iface}").stdout.strip() == "active"
    peers = []
    for p in wg["peers"]:
        st = live.get(p["public_key"], {})
        peers.append({
            "id": p["id"],
            "name": p["name"],
            "type": p["type"],
            "enabled": p["enabled"],
            "address": p["address"],
            "public_key": p["public_key"],
            "has_private_key": bool(p["private_key"]),
            "site_subnets": p["site_subnets"],
            "endpoint": p.get("endpoint", ""),
            "full_tunnel": p.get("full_tunnel", True),
            "live_endpoint": st.get("endpoint", ""),
            "last_handshake": st.get("last_handshake", 0),
            "rx_bytes": st.get("rx_bytes", 0),
            "tx_bytes": st.get("tx_bytes", 0),
            "online": bool(st.get("last_handshake", 0)),
        })
    return {
        "enabled": wg["enabled"],
        "interface": iface,
        "listen_port": wg["listen_port"],
        "address": wg["address"],
        "dns": wg["dns"],
        "endpoint_host": wg["endpoint_host"],
        "effective_endpoint": effective_endpoint(wg) if wg["enabled"] else None,
        "mtu": wg["mtu"],
        "public_key": wg["public_key"],
        "unit_active": unit_active,
        "wan_iface": _wan_iface(),
        "peers": peers,
    }
