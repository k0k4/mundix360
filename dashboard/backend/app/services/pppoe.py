"""PPPoE WAN authentication (pppd + rp-pppoe) for one or more ISP links.

Why this exists
---------------
Many Brazilian ISPs (fibre/GPON, radio/WISP) hand the link off over PPPoE: the
appliance must *authenticate* with a username/password to obtain its public IP
and default route, instead of getting an address by DHCP or static config. This
module makes the firewall a first-class PPPoE client, exactly like the
"Interfaces → PPPoE" section of pfSense/OPNsense/RouterOS:

  * pick the physical NIC the ONT/modem is plugged into,
  * store the provider credentials securely,
  * dial the link (pppd, rp-pppoe plugin) and keep it up (persist + systemd),
  * obtain the public IP, peer gateway and (optionally) the ISP DNS,
  * make the resulting ``pppN`` interface the appliance WAN so NAT/routing and
    the managed firewall track it automatically.

Design
------
* **N links, deterministic interfaces.** Each link is pinned to a fixed PPP unit
  (``ppp0``, ``ppp1`` …) so its interface name is stable and predictable. Up to
  ``MAX_LINKS`` links are supported.
* **Persisted + idempotent.** State lives in ``/etc/mundix/pppoe.json`` (0600).
  Applying rewrites the peer files, the chap/pap secrets (inside a clearly
  delimited managed block, never touching other entries) and a single systemd
  template unit, then reconciles autostart.
* **Firewall-aware.** The link flagged as the default route pins the managed
  firewall WAN to its ``pppN`` interface (so masquerade + zone-forward rules
  follow it). A dedicated ``mundix_pppoe`` NAT table also masquerades every
  active ``ppp*`` interface, so outbound NAT works the instant a link is up.
* **Anti-lockout.** Never rewrites netplan and never touches the interface the
  operator's session arrives on; PPPoE only adds, it never strips existing IPs.
"""
from __future__ import annotations

import os
import re
import threading
import time
from typing import Any

from . import shell

MODEL_PATH = "/etc/mundix/pppoe.json"
PEERS_DIR = "/etc/ppp/peers"
SECRETS_FILES = ("/etc/ppp/chap-secrets", "/etc/ppp/pap-secrets")
UNIT_TEMPLATE_PATH = "/etc/systemd/system/mundix-pppoe@.service"
PEER_PREFIX = "mundix-"
PPPOE_NFT_TABLE = "mundix_pppoe"

# Managed-block markers inside the shared chap/pap secrets files.
_SECRETS_BEGIN = "# >>> mundix360 pppoe (managed) >>>"
_SECRETS_END = "# <<< mundix360 pppoe (managed) <<<"

MAX_LINKS = 16  # PPP units 0..15

_NIC_RE = re.compile(r"^[a-z][a-z0-9.@_-]{1,14}$")
_ID_RE = re.compile(r"^[0-9a-f]{8}$")

_lock = threading.RLock()
_monitor_thread: threading.Thread | None = None
_monitor_stop = threading.Event()


# ----------------------------------------------------------------- model -----

def _default_model() -> dict[str, Any]:
    return {"links": []}


def _norm_link(link: dict[str, Any], used_units: set[int]) -> dict[str, Any]:
    unit = link.get("unit")
    try:
        unit = int(unit)
    except (TypeError, ValueError):
        unit = None
    if unit is None or unit < 0 or unit >= MAX_LINKS or unit in used_units:
        unit = _first_free_unit(used_units)
    used_units.add(unit)
    return {
        "id": (link.get("id") or os.urandom(4).hex()),
        "name": (link.get("name") or link.get("nic") or "pppoe").strip()[:48],
        "nic": (link.get("nic") or "").strip(),
        "username": (link.get("username") or "").strip(),
        "password": link.get("password") or "",
        "unit": unit,
        "enabled": bool(link.get("enabled", True)),         # autostart on boot
        "default_route": bool(link.get("default_route", True)),
        "route_metric": int(link.get("route_metric") or 0),  # 0 = auto (unit+100)
        "use_peer_dns": bool(link.get("use_peer_dns", False)),
        "mtu": int(link.get("mtu") or 1492),
        "lcp_echo_interval": int(link.get("lcp_echo_interval") or 20),
        "lcp_echo_failure": int(link.get("lcp_echo_failure") or 3),
    }


def _first_free_unit(used: set[int]) -> int:
    for u in range(MAX_LINKS):
        if u not in used:
            return u
    raise ValueError(f"limite de {MAX_LINKS} links PPPoE atingido")


def load_model() -> dict[str, Any]:
    import json
    try:
        with open(MODEL_PATH) as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return _default_model()
    used: set[int] = set()
    links = [_norm_link(l, used) for l in raw.get("links", []) if l.get("nic")]
    return {"links": links}


def _save_model(model: dict[str, Any]) -> None:
    import json
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    tmp = MODEL_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(model, f, indent=2, ensure_ascii=False)
    os.chmod(tmp, 0o600)
    os.replace(tmp, MODEL_PATH)


# ------------------------------------------------------------- validation ----

def _validate_link(link: dict[str, Any], others: list[dict[str, Any]]) -> None:
    if not link["name"]:
        raise ValueError("informe um nome para o link")
    if not _NIC_RE.match(link["nic"]):
        raise ValueError(f"interface de rede inválida: {link['nic']}")
    live = _live_ifaces()
    if live and link["nic"] not in live:
        raise ValueError(f"a interface '{link['nic']}' não existe neste appliance")
    if not link["username"]:
        raise ValueError("informe o usuário (login) do PPPoE")
    if not link["password"]:
        raise ValueError("informe a senha do PPPoE")
    if any(c in link["username"] for c in '"\n\r'):
        raise ValueError("usuário contém caracteres inválidos")
    if any(c in link["password"] for c in '"\n\r'):
        raise ValueError("senha contém caracteres inválidos")
    if not (1280 <= link["mtu"] <= 1500):
        raise ValueError("MTU fora da faixa PPPoE (1280–1500, padrão 1492)")
    # The same NIC can carry only one PPPoE session.
    for o in others:
        if o["id"] != link["id"] and o["nic"] == link["nic"]:
            raise ValueError(
                f"a interface '{link['nic']}' já é usada pelo link '{o['name']}'")


def _live_ifaces() -> set[str]:
    try:
        from . import system
        return {i["interface"] for i in system.interfaces() if i.get("interface")}
    except Exception:
        return set()


# ----------------------------------------------------------- peer rendering --

def _peer_name(link: dict[str, Any]) -> str:
    return f"{PEER_PREFIX}{link['id']}"


def _peer_path(link: dict[str, Any]) -> str:
    return os.path.join(PEERS_DIR, _peer_name(link))


def _ppp_iface(link: dict[str, Any]) -> str:
    return f"ppp{link['unit']}"


def _render_peer(link: dict[str, Any]) -> str:
    metric = link["route_metric"] or (link["unit"] + 100)
    lines = [
        f"# Mundix360 PPPoE '{link['name']}' (id {link['id']}) — gerenciado pelo painel.",
        "# NÃO edite à mão; alterações serão sobrescritas.",
        f"plugin rp-pppoe.so {link['nic']}",
        f"unit {link['unit']}",
        f'name "{link["username"]}"',
        "noauth",
        "hide-password",
        "persist",
        "maxfail 0",
        "holdoff 5",
        "noipdefault",
        f"mtu {link['mtu']}",
        f"mru {link['mtu']}",
        f"lcp-echo-interval {link['lcp_echo_interval']}",
        f"lcp-echo-failure {link['lcp_echo_failure']}",
        # PPPoE links are point-to-point; keeping the session alive matters more
        # than negotiating compression niceties on flaky WISP links.
        "default-asyncmap",
        "noaccomp",
        "nopcomp",
    ]
    if link["default_route"]:
        lines.append("defaultroute")
        lines.append(f"defaultroute-metric {metric}")
    else:
        lines.append("nodefaultroute")
    if link["use_peer_dns"]:
        lines.append("usepeerdns")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------- secrets -----

def _write_secrets(model: dict[str, Any]) -> None:
    """Rewrite only the managed block in chap-secrets and pap-secrets so other
    (manual) credentials are preserved. ISPs may use PAP or CHAP; we provide
    both so authentication succeeds regardless."""
    block = [_SECRETS_BEGIN]
    for l in model["links"]:
        # format: client server secret IP-addresses
        block.append(f'"{l["username"]}" * "{l["password"]}" *')
    block.append(_SECRETS_END)
    managed = "\n".join(block) + "\n"
    for path in SECRETS_FILES:
        prev = ""
        if os.path.isfile(path):
            with open(path) as f:
                prev = f.read()
        stripped = _strip_managed_block(prev)
        if stripped and not stripped.endswith("\n"):
            stripped += "\n"
        content = stripped + managed
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(content)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)


def _strip_managed_block(text: str) -> str:
    out: list[str] = []
    skip = False
    for line in text.splitlines():
        if line.strip() == _SECRETS_BEGIN:
            skip = True
            continue
        if line.strip() == _SECRETS_END:
            skip = False
            continue
        if not skip:
            out.append(line)
    return "\n".join(out).rstrip("\n") + ("\n" if out else "")


# --------------------------------------------------------------- systemd -----

_UNIT_TEMPLATE = """[Unit]
Description=Mundix360 PPPoE link %i
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/sbin/pppd call mundix-%i nodetach
Restart=always
RestartSec=5
TimeoutStopSec=15

[Install]
WantedBy=multi-user.target
"""


def _install_unit() -> None:
    """Install the systemd template unit (idempotent) and reload the daemon."""
    existing = ""
    if os.path.isfile(UNIT_TEMPLATE_PATH):
        with open(UNIT_TEMPLATE_PATH) as f:
            existing = f.read()
    if existing != _UNIT_TEMPLATE:
        tmp = UNIT_TEMPLATE_PATH + ".tmp"
        with open(tmp, "w") as f:
            f.write(_UNIT_TEMPLATE)
        os.chmod(tmp, 0o644)
        os.replace(tmp, UNIT_TEMPLATE_PATH)
        shell.run(["systemctl", "daemon-reload"], timeout=20)


def _unit(link: dict[str, Any]) -> str:
    return f"mundix-pppoe@{link['id']}.service"


# ------------------------------------------------------------- live status ---

def _ppp_live(iface: str) -> dict[str, Any]:
    """Live view of a ppp interface: up?, local/remote IP, since (uptime)."""
    out: dict[str, Any] = {"iface": iface, "up": False, "local_ip": None,
                           "remote_ip": None}
    r = shell.run(["ip", "-o", "-4", "addr", "show", "dev", iface], timeout=8)
    if not r.ok or "inet" not in r.stdout:
        return out
    parts = r.stdout.split()
    if "inet" in parts:
        i = parts.index("inet")
        out["local_ip"] = parts[i + 1].split("/")[0]
        # point-to-point peer follows "peer"
        if "peer" in parts:
            out["remote_ip"] = parts[parts.index("peer") + 1].split("/")[0]
    out["up"] = bool(out["local_ip"])
    return out


def _ppp_default_metric(iface: str) -> int | None:
    r = shell.run(["ip", "-o", "route", "show", "default", "dev", iface], timeout=8)
    for line in r.stdout.splitlines():
        p = line.split()
        if "metric" in p:
            try:
                return int(p[p.index("metric") + 1])
            except (ValueError, IndexError):
                return 0
        if p[:1] == ["default"]:
            return 0
    return None


def _unit_active(link: dict[str, Any]) -> bool:
    r = shell.run(["systemctl", "is-active", _unit(link)], timeout=8)
    return r.stdout.strip() == "active"


def _unit_enabled(link: dict[str, Any]) -> bool:
    r = shell.run(["systemctl", "is-enabled", _unit(link)], timeout=8)
    return r.stdout.strip() == "enabled"


def _link_status(link: dict[str, Any]) -> dict[str, Any]:
    iface = _ppp_iface(link)
    live = _ppp_live(iface)
    return {
        "id": link["id"],
        "name": link["name"],
        "nic": link["nic"],
        "username": link["username"],
        "unit": link["unit"],
        "iface": iface,
        "enabled": link["enabled"],
        "default_route": link["default_route"],
        "route_metric": link["route_metric"] or (link["unit"] + 100),
        "use_peer_dns": link["use_peer_dns"],
        "mtu": link["mtu"],
        "service_active": _unit_active(link),
        "autostart": _unit_enabled(link),
        "up": live["up"],
        "local_ip": live["local_ip"],
        "remote_ip": live["remote_ip"],
        "is_default": _ppp_default_metric(iface) is not None and live["up"],
    }


def get_status() -> dict[str, Any]:
    model = load_model()
    links = [_link_status(l) for l in model["links"]]
    return {"count": len(links), "links": links}


# ---------------------------------------------------------------- apply ------

def _apply_files(model: dict[str, Any]) -> None:
    """Render every peer file + secrets + the systemd unit. Removes orphaned
    peer files we previously managed for links that no longer exist."""
    os.makedirs(PEERS_DIR, exist_ok=True)
    _install_unit()
    _write_secrets(model)
    keep = {_peer_name(l) for l in model["links"]}
    for l in model["links"]:
        path = _peer_path(l)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(_render_peer(l))
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        # PPPoE runs over a raw ethernet socket; the NIC must be UP (it carries
        # no IP of its own). rp-pppoe doesn't always raise the link itself.
        shell.run(["ip", "link", "set", "dev", l["nic"], "up"], timeout=8)
    # prune orphans we own
    for fn in os.listdir(PEERS_DIR):
        if fn.startswith(PEER_PREFIX) and fn not in keep:
            try:
                os.remove(os.path.join(PEERS_DIR, fn))
            except OSError:
                pass


def _sync_autostart(model: dict[str, Any]) -> None:
    for l in model["links"]:
        unit = _unit(l)
        if l["enabled"]:
            shell.run(["systemctl", "enable", unit], timeout=15)
        else:
            shell.run(["systemctl", "disable", unit], timeout=15)


# -------------------------------------------------------------- firewall -----

def _apply_nat(model: dict[str, Any]) -> None:
    """Dedicated NAT table masquerading every active ppp interface, isolated
    from the managed firewall so outbound NAT works the instant a link is up."""
    ifaces = sorted({_ppp_iface(l) for l in model["links"]})
    _delete_nat()
    if not ifaces:
        return
    # nft supports trailing wildcard; an explicit set is clearer and exact.
    oifset = "{ " + ", ".join(f'"{i}"' for i in ifaces) + " }"
    rules = (
        f"table ip {PPPOE_NFT_TABLE} {{\n"
        f"    chain postrouting {{\n"
        f"        type nat hook postrouting priority 95; policy accept;\n"
        f"        oifname {oifset} masquerade\n"
        f"    }}\n"
        f"}}\n"
    )
    shell.run(["nft", "-f", "-"], input_text=rules, timeout=10)


def _delete_nat() -> None:
    shell.run(["nft", "delete", "table", "ip", PPPOE_NFT_TABLE], timeout=8)


def _nat_present() -> bool:
    r = shell.run(["nft", "list", "table", "ip", PPPOE_NFT_TABLE], timeout=8)
    return r.ok


def _active_default_iface(model: dict[str, Any]) -> str | None:
    """The connected PPPoE link that should own the firewall WAN: the up link
    flagged default_route with the lowest metric."""
    candidates: list[tuple[int, str]] = []
    for l in model["links"]:
        if not l["default_route"]:
            continue
        iface = _ppp_iface(l)
        if _ppp_live(iface)["up"]:
            metric = l["route_metric"] or (l["unit"] + 100)
            candidates.append((metric, iface))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


def _sync_firewall(model: dict[str, Any]) -> None:
    """Keep outbound NAT and the managed-firewall WAN tracking the active link.
    Pins the WAN only when it actually changes, to avoid needless re-renders."""
    _apply_nat(model)
    target = _active_default_iface(model)
    if not target:
        return
    try:
        from . import fwmanage
        pinned = (fwmanage.load_model().get("wan_iface") or "").strip()
        if pinned != target:
            fwmanage.set_wan(target)
    except Exception:
        pass


def _track_firewall(model: dict[str, Any]) -> None:
    """Lightweight monitor tick: re-add the NAT table only if it went missing
    (e.g. after a firewall reconcile flushed unrelated tables) and re-pin the
    WAN only when the active link actually changed. Avoids per-tick churn."""
    if model["links"] and not _nat_present():
        _apply_nat(model)
    target = _active_default_iface(model)
    if not target:
        return
    try:
        from . import fwmanage
        pinned = (fwmanage.load_model().get("wan_iface") or "").strip()
        if pinned != target:
            fwmanage.set_wan(target)
    except Exception:
        pass


def apply_all() -> dict[str, Any]:
    """Render config, reconcile autostart and firewall NAT/WAN. Does not force a
    (re)dial of already-running links."""
    with _lock:
        model = load_model()
        _apply_files(model)
        _sync_autostart(model)
        _sync_firewall(model)
    return get_status()


# --------------------------------------------------------------- CRUD --------

def save_link(data: dict[str, Any], *, create: bool) -> dict[str, Any]:
    with _lock:
        model = load_model()
        if create:
            used = {l["unit"] for l in model["links"]}
            link = _norm_link(data, used)
        else:
            if not _ID_RE.match(data.get("id") or ""):
                raise ValueError("id inválido")
            existing = next((l for l in model["links"] if l["id"] == data["id"]), None)
            if not existing:
                raise ValueError("link PPPoE não encontrado")
            merged = {**existing, **data, "unit": existing["unit"]}
            used = {l["unit"] for l in model["links"] if l["id"] != data["id"]}
            link = _norm_link(merged, used)
        _validate_link(link, model["links"])
        if create:
            model["links"].append(link)
        else:
            model["links"] = [link if l["id"] == link["id"] else l
                              for l in model["links"]]
        _save_model(model)
        _apply_files(model)
        _sync_autostart(model)
        # Reflect credential/peer changes on a running session immediately.
        if not create and _unit_active(link):
            shell.run(["systemctl", "restart", _unit(link)], timeout=30)
            time.sleep(2)
        _sync_firewall(model)
    return _link_status(link)


def delete_link(link_id: str) -> dict[str, Any]:
    if not _ID_RE.match(link_id or ""):
        raise ValueError("id inválido")
    with _lock:
        model = load_model()
        link = next((l for l in model["links"] if l["id"] == link_id), None)
        if not link:
            raise ValueError("link PPPoE não encontrado")
        unit = _unit(link)
        shell.run(["systemctl", "disable", "--now", unit], timeout=30)
        was_wan = _ppp_iface(link)
        model["links"] = [l for l in model["links"] if l["id"] != link_id]
        _save_model(model)
        _apply_files(model)
        try:
            os.remove(_peer_path(link))
        except OSError:
            pass
        # If the deleted link owned the firewall WAN, restore auto-detection.
        try:
            from . import fwmanage
            if (fwmanage.load_model().get("wan_iface") or "").strip() == was_wan:
                fwmanage.set_wan("")
        except Exception:
            pass
        _sync_firewall(model)
    return {"ok": True, "id": link_id}


# ------------------------------------------------------------- lifecycle -----

def _link_or_raise(link_id: str) -> dict[str, Any]:
    if not _ID_RE.match(link_id or ""):
        raise ValueError("id inválido")
    link = next((l for l in load_model()["links"] if l["id"] == link_id), None)
    if not link:
        raise ValueError("link PPPoE não encontrado")
    return link


def connect(link_id: str) -> dict[str, Any]:
    link = _link_or_raise(link_id)
    with _lock:
        model = load_model()
        _apply_files(model)  # ensure peer/secrets are current before dialling
        r = shell.run(["systemctl", "start", _unit(link)], timeout=40)
        if not r.ok:
            raise RuntimeError(f"falha ao iniciar o link: {(r.stderr or r.stdout).strip()}")
        # Give pppd a few seconds to negotiate so the UI reflects the new state.
        for _ in range(8):
            time.sleep(1)
            if _ppp_live(_ppp_iface(link))["up"]:
                break
        _sync_firewall(model)
    return _link_status(link)


def disconnect(link_id: str) -> dict[str, Any]:
    link = _link_or_raise(link_id)
    with _lock:
        shell.run(["systemctl", "stop", _unit(link)], timeout=30)
        iface = _ppp_iface(link)
        try:
            from . import fwmanage
            if (fwmanage.load_model().get("wan_iface") or "").strip() == iface:
                # Hand the WAN to another active PPPoE link, else auto-detect.
                model = load_model()
                other = _active_default_iface(
                    {"links": [l for l in model["links"] if l["id"] != link_id]})
                fwmanage.set_wan(other or "")
        except Exception:
            pass
        _sync_firewall(load_model())
    return _link_status(link)


def set_enabled(link_id: str, enabled: bool) -> dict[str, Any]:
    """Toggle boot autostart (and start/stop now to match)."""
    with _lock:
        model = load_model()
        link = next((l for l in model["links"] if l["id"] == link_id), None)
        if not link:
            raise ValueError("link PPPoE não encontrado")
        link["enabled"] = bool(enabled)
        _save_model(model)
        unit = _unit(link)
        if enabled:
            shell.run(["systemctl", "enable", "--now", unit], timeout=40)
        else:
            shell.run(["systemctl", "disable", "--now", unit], timeout=30)
        _sync_firewall(model)
    return _link_status(link)


# ----------------------------------------------------------------- logs ------

def link_logs(link_id: str, lines: int = 200) -> dict[str, Any]:
    link = _link_or_raise(link_id)
    lines = max(20, min(int(lines), 2000))
    unit = _unit(link)
    r = shell.run(
        ["journalctl", "-u", unit, "--no-pager", "-o", "short-iso", "-n", str(lines)],
        timeout=15)
    out: list[str] = []
    for ln in (r.stdout or "").splitlines():
        if "-- No entries --" in ln:
            continue
        out.append(ln)
    return {"unit": unit, "name": link["name"], "iface": _ppp_iface(link),
            "active": _unit_active(link), "lines": out}


# --------------------------------------------------------- discovery test ----

def discover(nic: str, timeout_s: int = 6) -> dict[str, Any]:
    """Probe a NIC for a PPPoE access concentrator (PADI/PADO), like a link
    test before saving credentials. Best-effort; requires the NIC to be up."""
    if not _NIC_RE.match(nic or ""):
        raise ValueError(f"interface inválida: {nic}")
    shell.run(["ip", "link", "set", "dev", nic, "up"], timeout=8)
    r = shell.run(["pppoe-discovery", "-I", nic, "-t", str(max(2, timeout_s))],
                  timeout=timeout_s + 6)
    text = (r.stdout or "") + (r.stderr or "")
    found = "Access-Concentrator" in text or "AC-Name" in text
    return {"nic": nic, "found": found, "output": text.strip()[:4000]}


# ------------------------------------------------------- startup / monitor ---

def _monitor_loop() -> None:
    while not _monitor_stop.is_set():
        try:
            model = load_model()
            if model["links"]:
                with _lock:
                    _track_firewall(model)
        except Exception:
            pass
        _monitor_stop.wait(20)


def start_monitor() -> None:
    """Install the unit on boot and keep NAT/WAN tracking the active link. No-op
    when no PPPoE link is configured."""
    global _monitor_thread
    with _lock:
        try:
            model = load_model()
            if not model["links"]:
                return
            _apply_files(model)
            _sync_firewall(model)
        except Exception:
            pass
        if _monitor_thread and _monitor_thread.is_alive():
            return
        _monitor_stop.clear()
        _monitor_thread = threading.Thread(target=_monitor_loop, daemon=True,
                                           name="pppoe-monitor")
        _monitor_thread.start()
