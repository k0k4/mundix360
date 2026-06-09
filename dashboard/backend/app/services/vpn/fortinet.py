"""Fortinet SSL-VPN client (openfortivpn).

Unlike WireGuard/OpenVPN where the appliance is the **server**, here the
appliance is a **client** that dials a remote FortiGate SSL-VPN — typical
site-to-site where a Mundix box at a branch reaches the head-office FortiGate.
The LAN behind the appliance then reaches the remote subnets through the
tunnel.

Security model:

  * Credentials (username/password) are secrets: they live only in the model
    (``/etc/mundix/vpn.json`` 0600) and in the rendered openfortivpn config
    (``/etc/openfortivpn/mundix.conf`` 0600). Never logged, never returned.
  * The FortiGate certificate is **pinned** (TOFU): the operator fetches the
    sha256 digest via :func:`probe_certificate`, reviews it and saves it as
    ``trusted_cert``. We never enable ``--insecure-ssl``.
  * The tunnel interface is pinned (``pppd-ifname``) so the firewall fragments
    are deterministic. Forward/masquerade openings are produced as nft
    fragments consumed by ``fwmanage.render`` (policy-drop stays authoritative,
    anti-lockout preserved).

Lifecycle is delegated to the packaged ``openfortivpn@<instance>`` systemd
template (``Type=notify``, ``Restart=on-failure``); we only render the config
and start/stop the unit.
"""
from __future__ import annotations

import hashlib
import os
import re
import socket
import ssl
from typing import Any

from .. import shell
from . import model as _m

CONF_DIR = "/etc/openfortivpn"
INSTANCE = "mundix"
CONF_FILE = f"{CONF_DIR}/{INSTANCE}.conf"
UNIT = f"openfortivpn@{INSTANCE}"


# ----------------------------------------------------------- cert pinning -----

def probe_certificate(host: str, port: int = 443, timeout: int = 8) -> dict[str, Any]:
    """Fetch the leaf certificate of ``host:port`` and return its sha256 digest.

    The digest matches openfortivpn's ``trusted-cert`` format: lowercase hex
    sha256 over the DER-encoded certificate. No verification is performed (the
    point is to *show* the operator the fingerprint to pin), so this must never
    feed straight into a trust decision without operator confirmation.
    """
    host = (host or "").strip()
    if not host:
        raise ValueError("informe o host do gateway")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, int(port)), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                der = ssock.getpeercert(binary_form=True)
    except (OSError, ssl.SSLError) as e:
        raise RuntimeError(f"não foi possível obter o certificado de {host}:{port}: {e}")
    if not der:
        raise RuntimeError("o gateway não apresentou certificado")
    digest = hashlib.sha256(der).hexdigest()
    return {"host": host, "port": int(port), "trusted_cert": digest}


# ----------------------------------------------------------- config render ----

def render_config(f: dict[str, Any]) -> str:
    L: list[str] = []
    a = L.append
    a("# AUTO-GERADO pelo Mundix360 — não edite à mão (use o dashboard).")
    a(f"host = {f['gateway_host']}")
    a(f"port = {int(f['gateway_port'])}")
    a(f"username = {f['username']}")
    a(f"password = {f['password']}")
    if f.get("realm"):
        a(f"realm = {f['realm']}")
    if f.get("trusted_cert"):
        a(f"trusted-cert = {f['trusted_cert']}")
    a(f"set-dns = {1 if f.get('set_dns') else 0}")
    a("set-routes = 1")
    a(f"pppd-ifname = {f['iface']}")
    a(f"persistent = {10 if f.get('persistent', True) else 0}")
    return "\n".join(L) + "\n"


def _write_config(f: dict[str, Any]) -> None:
    os.makedirs(CONF_DIR, exist_ok=True)
    os.chmod(CONF_DIR, 0o700)
    tmp = CONF_FILE + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(render_config(f))
    os.chmod(tmp, 0o600)            # secret: VPN password in plain text
    os.replace(tmp, CONF_FILE)


def _remove_config() -> None:
    try:
        os.remove(CONF_FILE)
    except OSError:
        pass


# ------------------------------------------------------------- apply/state ----

def _systemctl(*args: str) -> shell.CommandResult:
    return shell.run(["systemctl", *args], timeout=30)


def apply_client(f: dict[str, Any]) -> dict[str, Any]:
    if f.get("enabled"):
        _write_config(f)
        _systemctl("enable", UNIT)
        r = _systemctl("restart", UNIT)
        ok = r.ok
        detail = "" if ok else (r.stderr.strip() or r.stdout.strip())
    else:
        _systemctl("stop", UNIT)
        _systemctl("disable", UNIT)
        _remove_config()
        ok, detail = True, ""
    _refresh_firewall()
    return {"applied": ok, "detail": detail}


def _refresh_firewall() -> None:
    try:
        from .. import fwmanage
        fwmanage.reapply()
    except Exception:
        pass


# ------------------------------------------------------------ nft fragments ---
# The appliance is a *client*: no inbound port is opened. We only let LAN
# traffic forward into the tunnel and masquerade it onto the pinned interface
# so the FortiGate sees a known source (the tunnel address).

def nft_input_accepts(wan: str | None = None) -> list[str]:
    return []


def nft_forward_accepts(wan: str | None = None) -> list[str]:
    try:
        f = _m.load_model()["fortinet"]
        if not f["enabled"]:
            return []
        dev = _m.v_ppp_iface(f["iface"])
        return [
            f'iifname "{dev}" accept  # mundix-vpn fortinet',
            f'oifname "{dev}" accept  # mundix-vpn fortinet',
        ]
    except Exception:
        return []


def nft_postrouting_masq(wan: str | None = None) -> list[str]:
    try:
        f = _m.load_model()["fortinet"]
        if not f["enabled"]:
            return []
        dev = _m.v_ppp_iface(f["iface"])
        return [f'oifname "{dev}" masquerade  # mundix-vpn fortinet']
    except Exception:
        return []


# ---------------------------------------------------------------- status ------

def _iface_up(dev: str) -> bool:
    r = shell.run(["ip", "-o", "link", "show", dev], timeout=8)
    if not r.ok or not r.stdout.strip():
        return False
    return "state UP" in r.stdout or "state UNKNOWN" in r.stdout


def _tunnel_address(dev: str) -> str:
    r = shell.run(["ip", "-o", "-4", "addr", "show", dev], timeout=8)
    if not r.ok:
        return ""
    m = re.search(r"\binet\s+(\S+)", r.stdout)
    return m.group(1) if m else ""


def status() -> dict[str, Any]:
    f = _m.load_model()["fortinet"]
    unit_active = False
    tunnel_up = False
    tunnel_address = ""
    if f["enabled"]:
        unit_active = _systemctl("is-active", UNIT).stdout.strip() == "active"
        dev = f["iface"]
        tunnel_up = _iface_up(dev)
        tunnel_address = _tunnel_address(dev) if tunnel_up else ""
    return {
        "enabled": f["enabled"],
        "gateway_host": f["gateway_host"],
        "gateway_port": f["gateway_port"],
        "username": f["username"],
        "realm": f["realm"],
        "iface": f["iface"],
        "remote_subnets": f.get("remote_subnets", []),
        "set_dns": f.get("set_dns", False),
        "persistent": f.get("persistent", True),
        "has_password": bool(f.get("password")),
        "has_trusted_cert": bool(f.get("trusted_cert")),
        "trusted_cert": f.get("trusted_cert", ""),
        "unit_active": unit_active,
        "tunnel_up": tunnel_up,
        "tunnel_address": tunnel_address,
    }
