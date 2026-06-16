"""OpenVPN *client* dial-out connections.

Unlike ``openvpn.py`` (where the appliance is the **server**), this module lets
the appliance act as an OpenVPN **client**: the operator imports a remote
server's ``.ovpn`` profile and the box dials out — the classic way to reach a
head-office / cloud OpenVPN concentrator from a branch firewall.

For each connection the operator can:

  * import the ``.ovpn`` profile (inline certs supported);
  * supply a username/password when the profile uses ``auth-user-pass``;
  * choose whether to **route the LAN** through the tunnel (NAT/forward);
  * scope which **remote subnets** are reachable and **block** specific ones,
    so the firewall rules stay easy to manage.

Design (mirrors ``fortinet.py``):

  * The tunnel device is **pinned** (``dev ovpncN``) so the nft fragments are
    deterministic and the anti-lockout policy-drop firewall is never at risk.
  * Credentials live only in the model (``vpn.json`` 0600) and the rendered
    auth file (0600); never logged, never returned.
  * Lifecycle is delegated to the packaged ``openvpn-client@<instance>``
    systemd template; we only render the config + start/stop the unit. VPN
    state can never break the firewall render (fragments fail safe to []).
"""
from __future__ import annotations

import ipaddress
import os
import re
from typing import Any

from .. import shell
from . import model as _m

CONF_DIR = "/etc/openvpn/client"
INSTANCE_PREFIX = "mxc-"

# Directives we always strip from the imported profile and re-assert ourselves,
# so the dial-out is deterministic and never blocks on an interactive prompt.
_STRIP_RE = re.compile(
    r"^\s*(dev|dev-type|dev-node|auth-user-pass|auth-nocache|"
    r"disable-dco|route-nopull|daemon|log|log-append|status)\b",
    re.IGNORECASE,
)
_REMOTE_RE = re.compile(
    r"^\s*remote\s+(\S+)(?:\s+(\d+))?(?:\s+(udp|tcp|udp6|tcp6|tcp-client))?",
    re.IGNORECASE | re.MULTILINE,
)


def _instance(c: dict[str, Any]) -> str:
    return f"{INSTANCE_PREFIX}{c['id']}"


def _unit(c: dict[str, Any]) -> str:
    return f"openvpn-client@{_instance(c)}"


def _conf_path(c: dict[str, Any]) -> str:
    return f"{CONF_DIR}/{_instance(c)}.conf"


def _auth_path(c: dict[str, Any]) -> str:
    return f"{CONF_DIR}/{_instance(c)}.auth"


# ------------------------------------------------------------- config render ---

def _cidr_to_route(cidr: str) -> str | None:
    """Return an OpenVPN ``route`` argument ('network netmask') for a v4 CIDR."""
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return None
    if net.version != 4:
        return None
    return f"{net.network_address} {net.netmask}"


def render_config(c: dict[str, Any]) -> str:
    """Render the effective client config: imported profile + pinned overrides."""
    dev = c.get("dev") or "ovpnc0"
    lines = [ln.rstrip("\r") for ln in (c.get("config") or "").splitlines()]
    kept = [ln for ln in lines if not _STRIP_RE.match(ln)]

    out: list[str] = []
    out.append("# AUTO-GERADO pelo Mundix360 — perfil importado + ajustes do firewall.")
    out.append("# Não edite à mão; use o painel (Rede/VPN » OpenVPN Cliente).")
    out.append(f"dev {dev}")
    out.append("dev-type tun")
    out.append("disable-dco")          # keep the named tun deterministic for nft
    out.append("auth-nocache")
    out.append("pull-filter ignore \"redirect-gateway\"" if not c.get("route_lan")
               else "# redirect-gateway permitido (route_lan)")
    if c.get("username") and c.get("password"):
        out.append(f"auth-user-pass {_auth_path(c)}")
    if not c.get("accept_pushed_routes", True):
        out.append("route-nopull")
    out.extend(kept)
    # Explicit routes for the remote subnets the operator declared, so they exist
    # even when the server doesn't push them.
    for s in c.get("remote_subnets", []):
        r = _cidr_to_route(s)
        if r:
            out.append(f"route {r}")
    return "\n".join(out).rstrip() + "\n"


def _write(c: dict[str, Any]) -> None:
    os.makedirs(CONF_DIR, exist_ok=True)
    conf = _conf_path(c)
    tmp = conf + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(render_config(c))
    os.chmod(tmp, 0o600)               # may embed inline private keys
    os.replace(tmp, conf)
    auth = _auth_path(c)
    if c.get("username") and c.get("password"):
        atmp = auth + ".tmp"
        with open(atmp, "w") as fh:
            fh.write(f"{c['username']}\n{c['password']}\n")
        os.chmod(atmp, 0o600)          # secret: VPN credentials
        os.replace(atmp, auth)
    else:
        _safe_unlink(auth)


def _safe_unlink(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _remove_files(c: dict[str, Any]) -> None:
    _safe_unlink(_conf_path(c))
    _safe_unlink(_auth_path(c))


# --------------------------------------------------------------- apply/state ---

def _systemctl(*args: str) -> shell.CommandResult:
    return shell.run(["systemctl", *args], timeout=30)


def apply_client(c: dict[str, Any]) -> dict[str, Any]:
    """Render + (re)start or stop a single connection, then refresh the firewall."""
    if c.get("enabled"):
        _write(c)
        _systemctl("enable", _unit(c))
        r = _systemctl("restart", _unit(c))
        ok = r.ok
        detail = "" if ok else (r.stderr.strip() or r.stdout.strip())
    else:
        _systemctl("stop", _unit(c))
        _systemctl("disable", _unit(c))
        _remove_files(c)
        ok, detail = True, ""
    _refresh_firewall()
    return {"applied": ok, "detail": detail}


def teardown(c: dict[str, Any]) -> None:
    """Stop + disable + drop files for a removed connection."""
    _systemctl("stop", _unit(c))
    _systemctl("disable", _unit(c))
    _remove_files(c)
    _refresh_firewall()


def _refresh_firewall() -> None:
    try:
        from .. import fwmanage
        fwmanage.reapply()
    except Exception:
        pass


# --------------------------------------------------------------- nft fragments -
# The appliance is the *client*: no inbound port is opened. When the operator
# routes the LAN through a tunnel we let traffic forward into it (scoped to the
# declared remote subnets), drop the blocked subnets first, and masquerade onto
# the pinned device so the remote sees a single known source.

def _enabled_routed() -> list[dict[str, Any]]:
    try:
        clients = _m.load_model()["ovpn_clients"]
    except Exception:
        return []
    return [c for c in clients if c.get("enabled") and c.get("route_lan") and c.get("dev")]


def _daddr_match(cidr: str) -> str | None:
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return None
    return f"{'ip6' if net.version == 6 else 'ip'} daddr {net.with_prefixlen}"


def nft_input_accepts(wan: str | None = None) -> list[str]:
    return []


def nft_forward_accepts(wan: str | None = None) -> list[str]:
    out: list[str] = []
    for c in _enabled_routed():
        dev = _m.v_ovpnc(c["dev"])
        tag = f"# mundix-ovpnc {c['name']}"
        # Blocks first (evaluated top-down before the accepts below).
        for b in c.get("block_subnets", []):
            m = _daddr_match(b)
            if m:
                out.append(f'oifname "{dev}" {m} drop  {tag} bloqueio')
        # Return path from the tunnel into the LAN.
        out.append(f'iifname "{dev}" accept  {tag}')
        # LAN into the tunnel — scoped to the declared remote subnets when given.
        subs = [s for s in (c.get("remote_subnets") or []) if _daddr_match(s)]
        if subs:
            for s in subs:
                out.append(f'oifname "{dev}" {_daddr_match(s)} accept  {tag}')
        else:
            out.append(f'oifname "{dev}" accept  {tag}')
    return out


def nft_postrouting_masq(wan: str | None = None) -> list[str]:
    out: list[str] = []
    for c in _enabled_routed():
        dev = _m.v_ovpnc(c["dev"])
        out.append(f'oifname "{dev}" masquerade  # mundix-ovpnc {c["name"]}')
    return out


# ------------------------------------------------------------------- status ----

def parse_remote(config: str) -> dict[str, Any]:
    m = _REMOTE_RE.search(config or "")
    if not m:
        return {"host": "", "port": None, "proto": ""}
    proto = (m.group(3) or "").lower().replace("-client", "")
    return {"host": m.group(1), "port": int(m.group(2)) if m.group(2) else None,
            "proto": proto}


def _iface_up(dev: str) -> bool:
    r = shell.run(["ip", "-o", "link", "show", dev], timeout=8)
    if not r.ok or not r.stdout.strip():
        return False
    return "state UP" in r.stdout or "state UNKNOWN" in r.stdout


def _tunnel_address(dev: str) -> str:
    r = shell.run(["ip", "-o", "-4", "addr", "show", dev], timeout=8)
    if not r.ok:
        return ""
    mt = re.search(r"\binet\s+(\S+)", r.stdout)
    return mt.group(1) if mt else ""


def _client_status(c: dict[str, Any]) -> dict[str, Any]:
    remote = parse_remote(c.get("config", ""))
    unit_active = False
    tunnel_up = False
    tunnel_address = ""
    if c.get("enabled"):
        unit_active = _systemctl("is-active", _unit(c)).stdout.strip() == "active"
        dev = c.get("dev") or ""
        if dev:
            tunnel_up = _iface_up(dev)
            tunnel_address = _tunnel_address(dev) if tunnel_up else ""
    return {
        "id": c["id"],
        "name": c["name"],
        "description": c.get("description", ""),
        "enabled": c["enabled"],
        "dev": c.get("dev", ""),
        "route_lan": c.get("route_lan", False),
        "accept_pushed_routes": c.get("accept_pushed_routes", True),
        "remote_subnets": c.get("remote_subnets", []),
        "block_subnets": c.get("block_subnets", []),
        "remote_host": remote["host"],
        "remote_port": remote["port"],
        "remote_proto": remote["proto"],
        "username": c.get("username", ""),
        "has_password": bool(c.get("password")),
        "requires_auth": _m.ovpn_requires_auth(c.get("config", "")),
        "unit_active": unit_active,
        "tunnel_up": tunnel_up,
        "tunnel_address": tunnel_address,
    }


def status() -> list[dict[str, Any]]:
    try:
        clients = _m.load_model()["ovpn_clients"]
    except Exception:
        return []
    return [_client_status(c) for c in clients]
