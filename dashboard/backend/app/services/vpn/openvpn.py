"""OpenVPN server management (remote-access + site-to-site).

The appliance is the OpenVPN **server**. Security model:

  * A per-appliance PKI built with easy-rsa using **EC (prime256v1)** keys — fast
    even on the Atom and modern. CA + server cert live under
    ``/etc/mundix/openvpn/pki``; each client gets its own cert/key.
  * **tls-crypt** wraps the control channel with a single shared key, so the PKI
    is invisible to scanners and DoS on the port is blunted.
  * Client revocation is real: deleting a client revokes its cert and
    regenerates the CRL (``crl-verify``), so access is cut even if the client
    keeps its key.

Like WireGuard, the firewall openings (input port, tun forward, masquerade) are
produced as nft fragments consumed by ``fwmanage.render`` — the policy-drop
firewall stays the single source of truth and anti-lockout is preserved.
"""
from __future__ import annotations

import ipaddress
import os
import re
from typing import Any

from .. import shell
from . import model as _m

EASYRSA = "/usr/share/easy-rsa/easyrsa"
BASE_DIR = "/etc/mundix/openvpn"
PKI_DIR = f"{BASE_DIR}/pki"
TC_KEY = f"{BASE_DIR}/tc.key"
SERVER_CONF = "/etc/openvpn/server/mundix.conf"
CCD_DIR = "/etc/openvpn/ccd"
STATUS_FILE = "/run/openvpn-server/status-mundix.log"
UNIT = "openvpn-server@mundix"

_CN_RE = re.compile(r"[^A-Za-z0-9._-]+")


# ----------------------------------------------------------- key/PKI layer ----

def _easyrsa(*args: str, req_cn: str | None = None, timeout: int = 60) -> shell.CommandResult:
    cmd = [EASYRSA, "--pki-dir=" + PKI_DIR, "--batch"]
    if req_cn:
        cmd.append("--req-cn=" + req_cn)
    cmd.extend(args)
    return shell.run(cmd, timeout=timeout)


def _write_vars() -> None:
    vars_path = f"{PKI_DIR}/vars"
    with open(vars_path, "w") as f:
        f.write(
            "set_var EASYRSA_ALGO ec\n"
            "set_var EASYRSA_CURVE prime256v1\n"
            "set_var EASYRSA_CA_EXPIRE 3650\n"
            "set_var EASYRSA_CERT_EXPIRE 1080\n"
            "set_var EASYRSA_DN cn_only\n"
        )


def pki_ready() -> bool:
    return (os.path.isfile(f"{PKI_DIR}/ca.crt")
            and os.path.isfile(f"{PKI_DIR}/issued/mundix-server.crt")
            and os.path.isfile(TC_KEY))


def ensure_pki() -> None:
    """Build the CA, server cert, CRL and tls-crypt key once. Idempotent."""
    if pki_ready():
        return
    os.makedirs(BASE_DIR, exist_ok=True)
    os.chmod(BASE_DIR, 0o755)
    r = _easyrsa("init-pki")
    if not r.ok:
        raise RuntimeError(f"easyrsa init-pki falhou: {r.stderr.strip()}")
    _write_vars()
    r = _easyrsa("build-ca", "nopass", req_cn="Mundix-VPN-CA")
    if not r.ok:
        raise RuntimeError(f"easyrsa build-ca falhou: {r.stderr.strip()}")
    r = _easyrsa("build-server-full", "mundix-server", "nopass")
    if not r.ok:
        raise RuntimeError(f"easyrsa build-server falhou: {r.stderr.strip()}")
    _easyrsa("gen-crl")
    if not os.path.isfile(TC_KEY):
        g = shell.run(["openvpn", "--genkey", "secret", TC_KEY], timeout=15)
        if not g.ok:
            raise RuntimeError(f"falha ao gerar tls-crypt: {g.stderr.strip()}")
    os.chmod(f"{PKI_DIR}/crl.pem", 0o644)


def _cn_issued(cn: str) -> bool:
    return os.path.isfile(f"{PKI_DIR}/issued/{cn}.crt")


def build_client(cn: str) -> None:
    if _cn_issued(cn):
        return
    r = _easyrsa("build-client-full", cn, "nopass")
    if not r.ok:
        raise RuntimeError(f"emissão de certificado falhou para '{cn}': {r.stderr.strip()}")


def revoke_client(cn: str) -> None:
    if not _cn_issued(cn):
        return
    _easyrsa("revoke", cn)
    _easyrsa("gen-crl")
    if os.path.isfile(f"{PKI_DIR}/crl.pem"):
        os.chmod(f"{PKI_DIR}/crl.pem", 0o644)


def cn_for(name: str, existing: set[str]) -> str:
    base = _CN_RE.sub("-", name).strip("-") or "client"
    cn = base
    i = 1
    while cn in existing:
        i += 1
        cn = f"{base}-{i}"
    return cn


# ----------------------------------------------------------- live network -----

def _wan_iface() -> str | None:
    try:
        from .. import fwmanage
        return fwmanage._wan_iface() or None
    except Exception:
        return None


def _wan_ip() -> str | None:
    r = shell.run(["ip", "-o", "route", "get", "1.1.1.1"], timeout=8)
    m = re.search(r"\bsrc\s+(\S+)", r.stdout)
    return m.group(1) if m else None


def effective_endpoint_host(ov: dict[str, Any]) -> str | None:
    return (ov.get("endpoint_host") or "").strip() or _wan_ip()


def _lan_subnets() -> list[str]:
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


def _site_local_networks(c: dict[str, Any]) -> list[str]:
    """Networks on this appliance's side advertised to a site peer. Operators can
    pin them per site (local_networks); empty falls back to the discovered LANs."""
    return c.get("local_networks") or _lan_subnets()


# ----------------------------------------------------------- config render ----

def _net_mask(cidr: str) -> tuple[str, str]:
    net = ipaddress.ip_network(cidr, strict=False)
    return str(net.network_address), str(net.netmask)


def render_server_conf(ov: dict[str, Any]) -> str:
    proto = ov["proto"]
    dev = ov["dev"]
    net, mask = _net_mask(ov["subnet"])
    site_clients = [c for c in ov["clients"]
                    if c.get("enabled") and c.get("type") == "site" and c.get("site_subnets")]
    L: list[str] = []
    a = L.append
    a("# AUTO-GERADO pelo Mundix360 — não edite à mão (use o dashboard).")
    a(f"dev {dev}")
    a(f"proto {proto}")
    a(f"port {int(ov['port'])}")
    a("topology subnet")
    a(f"server {net} {mask}")
    a("keepalive 10 120")
    a("persist-key")
    a("persist-tun")
    a("user nobody")
    a("group nogroup")
    a(f"ca {PKI_DIR}/ca.crt")
    a(f"cert {PKI_DIR}/issued/mundix-server.crt")
    a(f"key {PKI_DIR}/private/mundix-server.key")
    a("dh none")
    a(f"tls-crypt {TC_KEY}")
    a(f"crl-verify {PKI_DIR}/crl.pem")
    a("data-ciphers AES-256-GCM:AES-128-GCM:CHACHA20-POLY1305")
    a("data-ciphers-fallback AES-256-GCM")
    a("auth SHA256")
    a("tls-version-min 1.2")
    a("remote-cert-tls client")
    if ov.get("dns"):
        for d in re.split(r"[,\s]+", ov["dns"].strip()):
            if d:
                a(f'push "dhcp-option DNS {d}"')
    # Per-client routing lives in the CCD (client-config-dir): road-warriors get
    # redirect-gateway / split routes, site peers get routes only to the local
    # networks they may reach. This stops a full-tunnel road-warrior setting from
    # leaking redirect-gateway onto a site-to-site router.
    enabled_clients = [c for c in ov["clients"] if c.get("enabled")]
    if enabled_clients:
        a(f"client-config-dir {CCD_DIR}")
    # Server-side kernel routes for each remote site subnet (paired with CCD iroute).
    for c in site_clients:
        for sub in c["site_subnets"]:
            n, m = _net_mask(sub)
            a(f"route {n} {m}")
    a(f"status {STATUS_FILE} 5")
    a("verb 3")
    if proto == "udp":
        a("explicit-exit-notify 1")
    return "\n".join(L) + "\n"


def _write_ccd(ov: dict[str, Any]) -> None:
    os.makedirs(CCD_DIR, exist_ok=True)
    # Rewrite the whole CCD dir from the model so removed clients don't linger.
    for fn in os.listdir(CCD_DIR):
        try:
            os.remove(os.path.join(CCD_DIR, fn))
        except OSError:
            pass
    full_tunnel = ov.get("full_tunnel", True)
    for c in ov["clients"]:
        if not c.get("enabled") or not c.get("cn"):
            continue
        lines: list[str] = []
        if c.get("type") == "site" and c.get("site_subnets"):
            # The server must know which client owns each remote subnet (iroute),
            # and the remote router must learn a route back to our local networks.
            for sub in c["site_subnets"]:
                n, m = _net_mask(sub)
                lines.append(f"iroute {n} {m}")
            for lan in _site_local_networks(c):
                n, m = _net_mask(lan)
                lines.append(f'push "route {n} {m}"')
        else:  # road-warrior: full tunnel or split routes to our LANs
            if full_tunnel:
                lines.append('push "redirect-gateway def1 bypass-dhcp"')
            else:
                for lan in _lan_subnets():
                    n, m = _net_mask(lan)
                    lines.append(f'push "route {n} {m}"')
        if lines:
            with open(os.path.join(CCD_DIR, c["cn"]), "w") as f:
                f.write("\n".join(lines) + "\n")


def _pem_block(text: str, begin: str, end: str) -> str:
    i = text.find(begin)
    j = text.find(end)
    if i == -1 or j == -1:
        return text.strip()
    return text[i:j + len(end)].strip()


def _read(path: str) -> str:
    with open(path) as f:
        return f.read()


def client_ovpn(ov: dict[str, Any], client: dict[str, Any]) -> str:
    cn = client["cn"]
    if not _cn_issued(cn):
        raise ValueError("certificado do cliente não encontrado")
    host = effective_endpoint_host(ov)
    if not host:
        raise ValueError("endpoint indisponível: defina o host público ou conecte a WAN")
    ca = _pem_block(_read(f"{PKI_DIR}/ca.crt"),
                    "-----BEGIN CERTIFICATE-----", "-----END CERTIFICATE-----")
    crt = _pem_block(_read(f"{PKI_DIR}/issued/{cn}.crt"),
                     "-----BEGIN CERTIFICATE-----", "-----END CERTIFICATE-----")
    key = _read(f"{PKI_DIR}/private/{cn}.key").strip()
    tc = _pem_block(_read(TC_KEY),
                    "-----BEGIN OpenVPN Static key V1-----",
                    "-----END OpenVPN Static key V1-----")
    L: list[str] = []
    a = L.append
    a("client")
    a("dev tun")
    a(f"proto {ov['proto']}")
    a(f"remote {host} {int(ov['port'])}")
    a("resolv-retry infinite")
    a("nobind")
    a("persist-key")
    a("persist-tun")
    a("remote-cert-tls server")
    a("data-ciphers AES-256-GCM:AES-128-GCM:CHACHA20-POLY1305")
    a("data-ciphers-fallback AES-256-GCM")
    a("auth SHA256")
    a("tls-version-min 1.2")
    a("verb 3")
    a(f"<ca>\n{ca}\n</ca>")
    a(f"<cert>\n{crt}\n</cert>")
    a(f"<key>\n{key}\n</key>")
    a(f"<tls-crypt>\n{tc}\n</tls-crypt>")
    return "\n".join(L) + "\n"


# ------------------------------------------------------------- apply/state ----

def _systemctl(*args: str) -> shell.CommandResult:
    return shell.run(["systemctl", *args], timeout=30)


def _write_server_conf(ov: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(SERVER_CONF), exist_ok=True)
    tmp = SERVER_CONF + ".tmp"
    with open(tmp, "w") as f:
        f.write(render_server_conf(ov))
    os.chmod(tmp, 0o600)
    os.replace(tmp, SERVER_CONF)


def apply_server(ov: dict[str, Any]) -> dict[str, Any]:
    if ov.get("enabled"):
        ensure_pki()
        for c in ov["clients"]:
            if c.get("enabled"):
                build_client(c["cn"])
        _write_ccd(ov)
        _write_server_conf(ov)
        _systemctl("enable", UNIT)
        r = _systemctl("restart", UNIT)
        ok = r.ok
        detail = "" if ok else (r.stderr.strip() or r.stdout.strip())
    else:
        _systemctl("stop", UNIT)
        _systemctl("disable", UNIT)
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

def nft_input_accepts(wan: str | None = None) -> list[str]:
    try:
        ov = _m.load_model()["openvpn"]
        if not ov["enabled"]:
            return []
        port = int(ov["port"])
        proto = ov["proto"]
        if proto not in ("udp", "tcp") or not (1 <= port <= 65535):
            return []
        return [f"{proto} dport {port} accept  # mundix-vpn openvpn"]
    except Exception:
        return []


def nft_forward_accepts(wan: str | None = None) -> list[str]:
    try:
        ov = _m.load_model()["openvpn"]
        if not ov["enabled"]:
            return []
        dev = _m.v_tun(ov["dev"])
        return [
            f'iifname "{dev}" accept  # mundix-vpn openvpn',
            f'oifname "{dev}" accept  # mundix-vpn openvpn',
        ]
    except Exception:
        return []


def nft_postrouting_masq(wan: str | None = None) -> list[str]:
    try:
        ov = _m.load_model()["openvpn"]
        if not ov["enabled"] or not wan:
            return []
        from .. import fwmanage
        wan_if = fwmanage._v_iface(wan)
        net = str(ipaddress.ip_network(ov["subnet"], strict=False))
        return [f'oifname "{wan_if}" ip saddr {net} masquerade  # mundix-vpn openvpn']
    except Exception:
        return []


# ---------------------------------------------------------------- status ------

def _parse_status() -> dict[str, dict[str, Any]]:
    """Parse the OpenVPN status file → {common_name: {real_address, rx, tx}}."""
    out: dict[str, dict[str, Any]] = {}
    try:
        text = _read(STATUS_FILE)
    except OSError:
        return out
    for line in text.splitlines():
        # status v1 default: "CLIENT_LIST,<CN>,<real>,<vaddr>,...,<rx>,<tx>,..."
        if line.startswith("CLIENT_LIST,"):
            f = line.split(",")
            if len(f) >= 7:
                out[f[1]] = {
                    "real_address": f[2],
                    "rx_bytes": int(f[5]) if f[5].isdigit() else 0,
                    "tx_bytes": int(f[6]) if f[6].isdigit() else 0,
                }
    return out


def status() -> dict[str, Any]:
    ov = _m.load_model()["openvpn"]
    live = _parse_status() if ov["enabled"] else {}
    unit_active = False
    if ov["enabled"]:
        unit_active = _systemctl("is-active", UNIT).stdout.strip() == "active"
    clients = []
    for c in ov["clients"]:
        st = live.get(c["cn"], {})
        clients.append({
            "id": c["id"],
            "name": c["name"],
            "cn": c["cn"],
            "type": c["type"],
            "enabled": c["enabled"],
            "site_subnets": c.get("site_subnets", []),
            "local_networks": c.get("local_networks", []),
            "description": c.get("description", ""),
            "has_cert": _cn_issued(c["cn"]),
            "real_address": st.get("real_address", ""),
            "rx_bytes": st.get("rx_bytes", 0),
            "tx_bytes": st.get("tx_bytes", 0),
            "online": bool(st),
        })
    return {
        "enabled": ov["enabled"],
        "proto": ov["proto"],
        "port": ov["port"],
        "subnet": ov["subnet"],
        "dev": ov["dev"],
        "dns": ov["dns"],
        "full_tunnel": ov.get("full_tunnel", True),
        "endpoint_host": ov["endpoint_host"],
        "effective_endpoint": (
            f"{effective_endpoint_host(ov)}:{ov['port']}" if ov["enabled"] else None),
        "pki_ready": pki_ready(),
        "unit_active": unit_active,
        "wan_iface": _wan_iface(),
        "clients": clients,
    }
