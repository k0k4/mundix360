"""Professional, adaptive interface & VLAN management backed by netplan.

This is the single source of truth for *layer-2/3 interface* configuration on the
appliance, equivalent to the "Interfaces" + "Interfaces > VLANs" sections of
pfSense/OPNsense/FortiGate. Everything is persisted to netplan YAML (networkd
renderer) and validated with `netplan generate` before being applied, so the
same image adapts to any hardware (4, 6, N NICs; ens/enp/eth names) and survives
reboots.

Capabilities:
  - Enumerate every NIC and VLAN sub-interface merging the *live* kernel state
    (`ip link`/`ip addr`) with the *persisted* netplan config.
  - Per-interface: friendly alias/description, admin enable/disable, IPv4 mode
    (DHCP / static CIDR + gateway / none), MTU, custom resolvers.
  - 802.1Q VLAN lifecycle: create/edit/delete (parent + tag 1-4094 + name).
  - WAN safety guards (never silently strip the uplink), timestamped backups and
    automatic rollback if netplan rejects or fails to apply a change.

Descriptions are stored in a small JSON sidecar because netplan has no native
"description" field — exactly how pfSense keeps interface descriptions separate
from the OS config.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import threading
import time
from typing import Any

import yaml

from ..config import settings
from . import shell, system

# Serialises every netplan mutation (backup -> write -> validate -> apply ->
# rollback) so concurrent API calls can't corrupt the network config.
_lock = threading.RLock()

IFNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._@-]{0,14}$")
VLAN_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,14}$")
RESERVED_NAMES = {"lo"}


# --------------------------------------------------------------- netplan io ---

def _netplan_files() -> list[str]:
    d = settings.netplan_dir
    if not os.path.isdir(d):
        return []
    return sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith((".yaml", ".yml")))


def _managed_file() -> str:
    """The single file we own and rewrite. Prefer an existing appliance config,
    otherwise fall back to a high-priority managed file."""
    files = _netplan_files()
    if files:
        return files[0]
    return os.path.join(settings.netplan_dir, "01-network-config-all.yaml")


def _load_model(strict: bool = False) -> dict[str, Any]:
    """Full netplan model from the managed file (creating a sane skeleton if the
    appliance has no netplan config yet). When ``strict`` (used by mutators), an
    unreadable/corrupt managed file is fatal — we must never overwrite a config
    we could not parse, or we would silently drop the WAN and every other NIC."""
    path = _managed_file()
    model: dict[str, Any] = {}
    if os.path.isfile(path):
        try:
            with open(path) as f:
                model = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            if strict:
                raise RuntimeError(
                    f"netplan {path} está ilegível/corrompido — conserte-o antes de "
                    f"alterar a rede pelo painel: {e}")
            model = {}
    net = model.setdefault("network", {})
    net.setdefault("version", 2)
    net.setdefault("renderer", "networkd")
    net.setdefault("ethernets", {})
    net.setdefault("vlans", {})
    return model


def _dump(model: dict[str, Any]) -> str:
    return yaml.safe_dump(model, sort_keys=False, default_flow_style=False)


def _validate(model: dict[str, Any]) -> tuple[bool, str]:
    """Validate the candidate config against ALL netplan files (so VLAN parents
    defined elsewhere still resolve) using `netplan generate --root-dir`."""
    import tempfile

    root = tempfile.mkdtemp(prefix="mundix-netplan-")
    try:
        dst = os.path.join(root, "etc", "netplan")
        os.makedirs(dst, exist_ok=True)
        managed = os.path.basename(_managed_file())
        for src in _netplan_files():
            if os.path.basename(src) == managed:
                continue
            shutil.copy(src, os.path.join(dst, os.path.basename(src)))
        cand = os.path.join(dst, managed)
        with open(cand, "w") as f:
            f.write(_dump(model))
        os.chmod(cand, 0o600)
        res = shell.run(["netplan", "generate", "--root-dir", root], timeout=30)
        if res.ok:
            return True, ""
        return False, (res.stderr or res.stdout).strip()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _backup() -> str | None:
    path = _managed_file()
    if not os.path.isfile(path):
        return None
    os.makedirs(settings.netplan_backup_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(settings.netplan_backup_dir, f"{os.path.basename(path)}.{ts}.bak")
    shutil.copy(path, dst)
    # keep only the 20 most recent backups
    baks = sorted(
        (os.path.join(settings.netplan_backup_dir, f) for f in os.listdir(settings.netplan_backup_dir)),
        key=os.path.getmtime,
    )
    for old in baks[:-20]:
        try:
            os.remove(old)
        except OSError:
            pass
    return dst


def _write(path: str, content: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(content)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _apply_model(model: dict[str, Any]) -> None:
    """Validate, back up, write and apply a netplan model. Rolls back to the
    previous config if netplan rejects or fails to apply the change."""
    ok, err = _validate(model)
    if not ok:
        raise ValueError(f"netplan rejeitou a configuração: {err}")
    path = _managed_file()
    prev = None
    if os.path.isfile(path):
        with open(path) as f:
            prev = f.read()
    backup = _backup()
    _write(path, _dump(model))
    gen = shell.run(["netplan", "generate"], timeout=30)
    apply = shell.run(["netplan", "apply"], timeout=45) if gen.ok else gen
    if not (gen.ok and apply.ok):
        # roll back to the last-known-good config and re-apply
        if prev is not None:
            _write(path, prev)
        elif os.path.isfile(path):
            os.remove(path)
        shell.run(["netplan", "apply"], timeout=45)
        detail = (apply.stderr or apply.stdout or gen.stderr or gen.stdout).strip()
        raise RuntimeError(
            f"netplan apply falhou e a configuração foi revertida"
            f"{f' (backup {backup})' if backup else ''}: {detail}")


# ----------------------------------------------------------- descriptions ----

def _load_meta() -> dict[str, Any]:
    path = settings.iface_meta_file
    if os.path.isfile(path):
        try:
            with open(path) as f:
                return json.load(f) or {}
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_meta(meta: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(settings.iface_meta_file), exist_ok=True)
    _write(settings.iface_meta_file, json.dumps(meta, indent=2))


# ------------------------------------------------------------- live state ----

def _live() -> dict[str, dict[str, Any]]:
    """Live kernel view per interface: state, mac, mtu, kind, parent, vlan id,
    and the addresses actually configured right now."""
    out: dict[str, dict[str, Any]] = {}
    res = shell.run(["ip", "-d", "-o", "link", "show"], timeout=8)
    for line in res.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        raw = parts[1].rstrip(":")
        name = raw.split("@")[0]
        parent = raw.split("@")[1] if "@" in raw else None
        if name == "lo":
            continue
        state = parts[parts.index("state") + 1].lower() if "state" in parts else "unknown"
        mtu = int(parts[parts.index("mtu") + 1]) if "mtu" in parts else None
        mac = parts[parts.index("link/ether") + 1] if "link/ether" in parts else ""
        kind = "ethernet"
        vlan_id = None
        if "vlan" in parts and "id" in parts:
            kind = "vlan"
            try:
                vlan_id = int(parts[parts.index("id") + 1])
            except (ValueError, IndexError):
                vlan_id = None
        # carrier: kernel reports NO-CARRIER in the flags field
        flags = line.split("<", 1)[1].split(">", 1)[0] if "<" in line else ""
        out[name] = {
            "state": state, "mtu": mtu, "mac": mac, "kind": kind,
            "parent": parent, "vlan_id": vlan_id,
            "carrier": "NO-CARRIER" not in flags,
            "admin_up": "UP" in flags.split(","),
            "addresses": [],
        }
    res_a = shell.run(["ip", "-o", "-4", "addr", "show"], timeout=8)
    for line in res_a.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1] in out:
            out[parts[1]]["addresses"].append(parts[3])
    return out


def _gateway_of(cfg: dict[str, Any]) -> str | None:
    for r in cfg.get("routes") or []:
        if r.get("to") in ("default", "0.0.0.0/0"):
            return r.get("via")
    return cfg.get("gateway4")


def _ipv4_mode(cfg: dict[str, Any]) -> str:
    if cfg.get("dhcp4") in (True, "yes", "true"):
        return "dhcp"
    if cfg.get("addresses"):
        return "static"
    return "none"


def _iface_for_ip(ip: str | None) -> str | None:
    """Which interface the kernel would use to reach ``ip`` — used to protect the
    interface that is currently carrying the operator's own dashboard session."""
    if not ip:
        return None
    res = shell.run(["ip", "-o", "route", "get", ip], timeout=8)
    parts = res.stdout.split()
    if "dev" in parts:
        return parts[parts.index("dev") + 1]
    return None


# --------------------------------------------------------------- public api ---

def list_interfaces() -> dict[str, Any]:
    """Rich, adaptive inventory of every NIC and VLAN merging live kernel state,
    persisted netplan config, friendly descriptions and firewall roles."""
    live = _live()
    model = _load_model()
    eth = model["network"].get("ethernets", {}) or {}
    vlans = model["network"].get("vlans", {}) or {}
    meta = _load_meta()

    # Firewall roles (WAN / zone) come from the adaptive firewall layer.
    roles: dict[str, dict[str, Any]] = {}
    wan = ""
    try:
        from . import fwmanage
        assign = fwmanage.interface_assignments()
        wan = assign.get("wan_iface", "")
        for i in assign.get("interfaces", []):
            roles[i["interface"]] = {"role": i.get("role"), "zone": i.get("zone")}
    except Exception:
        pass

    # PPPoE overlay: map physical NIC → PPPoE link info so the Interfaces
    # page can show the PPP-assigned IP alongside the physical interface.
    pppoe_map: dict[str, dict[str, Any]] = {}
    try:
        from . import pppoe as _pppoe
        for link in _pppoe.load_model().get("links", []):
            ppp_iface = f"ppp{link['unit']}"
            ppp_live = _pppoe._ppp_live(ppp_iface)
            pppoe_map[link["nic"]] = {
                "ppp_iface": ppp_iface,
                "ppp_name": link["name"],
                "ppp_up": ppp_live["up"],
                "ppp_local_ip": ppp_live["local_ip"],
                "ppp_remote_ip": ppp_live["remote_ip"],
                "ppp_default_route": link.get("default_route", False),
                "ppp_metric": link.get("route_metric") or (link["unit"] + 100),
            }
    except Exception:
        pass

    names = set(live) | set(eth) | set(vlans)
    items: list[dict[str, Any]] = []
    for name in sorted(names):
        lv = live.get(name, {})
        cfg = vlans.get(name) or eth.get(name) or {}
        is_vlan = name in vlans or lv.get("kind") == "vlan"
        item = {
            "interface": name,
            "kind": "vlan" if is_vlan else "ethernet",
            "description": (meta.get(name) or {}).get("description", ""),
            "state": lv.get("state", "unknown"),
            "carrier": lv.get("carrier"),
            "mac": lv.get("mac", ""),
            "mtu": cfg.get("mtu") or lv.get("mtu"),
            "addresses": lv.get("addresses", []),
            "configured": name in eth or name in vlans,
            "present": name in live,
            "admin_enabled": cfg.get("activation-mode") != "off",
            "ipv4_mode": _ipv4_mode(cfg),
            "static_addresses": cfg.get("addresses") or [],
            "gateway": _gateway_of(cfg),
            "nameservers": (cfg.get("nameservers") or {}).get("addresses", []),
            "role": roles.get(name, {}).get("role", "unassigned"),
            "zone": roles.get(name, {}).get("zone"),
            "is_wan": name == wan,
        }
        if is_vlan:
            item["vlan_id"] = (cfg.get("id") if cfg.get("id") is not None else lv.get("vlan_id"))
            item["parent"] = cfg.get("link") or lv.get("parent")
        items.append(item)

    items.sort(key=lambda i: (i["kind"] == "vlan", not i["is_wan"], i["state"] != "up", i["interface"]))
    return {"wan_iface": wan, "interfaces": items}


def get_interface(name: str) -> dict[str, Any] | None:
    return next((i for i in list_interfaces()["interfaces"] if i["interface"] == name), None)


def _section_for(model: dict[str, Any], name: str) -> tuple[dict[str, Any], str]:
    """Return (section_dict, kind) the interface lives in, defaulting to
    ethernets for a physical NIC."""
    if name in model["network"].get("vlans", {}):
        return model["network"]["vlans"], "vlan"
    return model["network"].setdefault("ethernets", {}), "ethernet"


def _validate_ipv4(mode: str, address: str | None, gateway: str | None,
                   nameservers: list[str]) -> None:
    if mode not in ("dhcp", "static", "none"):
        raise ValueError("modo IPv4 inválido (use dhcp, static ou none)")
    if mode == "static":
        if not address:
            raise ValueError("endereço estático obrigatório (ex.: 192.168.10.1/24)")
        try:
            iface = ipaddress.ip_interface(address)
        except ValueError:
            raise ValueError(f"endereço/CIDR inválido: {address}")
        if gateway:
            try:
                gw = ipaddress.ip_address(gateway)
            except ValueError:
                raise ValueError(f"gateway inválido: {gateway}")
            # Catch the most common lockout typo: a gateway outside the interface
            # subnet yields a default route networkd can't install.
            if gw not in iface.network:
                raise ValueError(
                    f"o gateway {gateway} está fora da sub-rede {iface.network}")
    for ns in nameservers:
        try:
            ipaddress.ip_address(ns)
        except ValueError:
            raise ValueError(f"servidor DNS inválido: {ns}")


def set_interface(name: str, *, description: str | None = None,
                  admin_enabled: bool | None = None, ipv4_mode: str | None = None,
                  address: str | None = None, gateway: str | None = None,
                  nameservers: list[str] | None = None, mtu: int | None = None,
                  force: bool = False, protect_iface: str | None = None) -> dict[str, Any]:
    """Update one interface (physical or VLAN). Only the provided fields change.
    Refuses to break the active WAN uplink, the interface carrying the operator's
    own session (``protect_iface``), or to add a competing default route on a
    non-WAN interface — unless force=True."""
    if not IFNAME_RE.match(name) or name in RESERVED_NAMES:
        raise ValueError(f"interface inválida: {name}")
    nameservers = [s for s in (nameservers or []) if s]

    # WAN guard — never silently strip the uplink that carries the default route.
    live_wan = system._default_route_iface()
    is_wan = name == live_wan
    destructive = admin_enabled is False or ipv4_mode in ("none",) or ipv4_mode == "dhcp"
    if not force:
        if is_wan:
            if admin_enabled is False:
                raise ValueError("esta é a interface WAN ativa — desabilitá-la cortaria a Internet")
            if ipv4_mode == "none":
                raise ValueError("a WAN precisa de IP (DHCP ou estático) — remover deixaria o appliance sem uplink")
            if ipv4_mode == "static" and not gateway:
                raise ValueError("a WAN estática precisa de um gateway")
        # Lockout guard: don't let the operator cut the very interface their
        # dashboard session is coming in on.
        if protect_iface and name == protect_iface and not is_wan and destructive:
            raise ValueError(
                f"{name} é a interface pela qual você está acessando o painel — "
                f"alterá-la assim te desconectaria. Faça isso por outra interface.")
        # A default route belongs to the WAN. Forbid it elsewhere so a routine
        # LAN/VLAN edit can't hijack outbound routing.
        if gateway and not is_wan:
            raise ValueError(
                "gateway/rota default só se aplica à interface WAN — "
                "uma interface interna não deve ter gateway")

    if ipv4_mode is not None:
        _validate_ipv4(ipv4_mode, address, gateway, nameservers)
    if mtu is not None and not (576 <= mtu <= 9216):
        raise ValueError("MTU fora da faixa (576–9216)")

    with _lock:
        if description is not None:
            meta = _load_meta()
            entry = meta.setdefault(name, {})
            entry["description"] = description.strip()[:64]
            _save_meta(meta)
            if all(v is None for v in (admin_enabled, ipv4_mode, mtu)):
                return get_interface(name) or {}

        model = _load_model(strict=True)
        section, _kind = _section_for(model, name)
        cfg = section.setdefault(name, {})

        if admin_enabled is not None:
            if admin_enabled:
                cfg.pop("activation-mode", None)
            else:
                cfg["activation-mode"] = "off"

        if mtu is not None:
            cfg["mtu"] = mtu

        if ipv4_mode is not None:
            cfg.pop("dhcp4", None)
            cfg.pop("addresses", None)
            cfg.pop("routes", None)
            cfg.pop("gateway4", None)  # legacy key — drop so stale routes don't linger
            cfg.pop("nameservers", None)
            if ipv4_mode == "dhcp":
                cfg["dhcp4"] = True
            elif ipv4_mode == "static":
                cfg["dhcp4"] = False
                cfg["addresses"] = [address]
                if gateway and is_wan:
                    cfg["routes"] = [{"to": "default", "via": gateway}]
                if nameservers:
                    cfg["nameservers"] = {"addresses": nameservers}
            else:  # none
                cfg["dhcp4"] = False

        _apply_model(model)
        # Reflect admin state on the live link immediately.
        if admin_enabled is not None:
            shell.run(["ip", "link", "set", name, "up" if admin_enabled else "down"], timeout=8)
    return get_interface(name) or {}


# -------------------------------------------------------------------- vlans ---

def list_vlans() -> list[dict[str, Any]]:
    return [i for i in list_interfaces()["interfaces"] if i["kind"] == "vlan"]


def create_vlan(*, parent: str, vlan_id: int, name: str | None = None,
                description: str = "", ipv4_mode: str = "none",
                address: str | None = None, gateway: str | None = None,
                nameservers: list[str] | None = None,
                mtu: int | None = None) -> dict[str, Any]:
    """Create an 802.1Q VLAN sub-interface (parent + tag), then optionally give
    it an IPv4 config. The new sub-interface becomes assignable to a zone."""
    nameservers = [s for s in (nameservers or []) if s]
    if not IFNAME_RE.match(parent):
        raise ValueError(f"interface pai inválida: {parent}")
    try:
        vlan_id = int(vlan_id)
    except (TypeError, ValueError):
        raise ValueError("VLAN ID deve ser um número")
    if not (1 <= vlan_id <= 4094):
        raise ValueError("VLAN ID fora da faixa 802.1Q (1–4094)")
    vname = (name or f"vlan{vlan_id}").strip()
    if not VLAN_NAME_RE.match(vname):
        raise ValueError("nome de VLAN inválido (minúsculas, ex.: vlan10, guest)")
    if gateway:
        # A VLAN segment is internal; a default route belongs to the WAN. Refuse
        # so creating a VLAN can't hijack the appliance's outbound routing.
        raise ValueError("uma VLAN interna não deve ter gateway/rota default")
    _validate_ipv4(ipv4_mode, address, None, nameservers)
    if mtu is not None and not (576 <= mtu <= 9216):
        raise ValueError("MTU fora da faixa (576–9216)")

    with _lock:
        model = _load_model(strict=True)
        vlans = model["network"].setdefault("vlans", {})
        if vname in vlans:
            raise ValueError(f"já existe uma VLAN chamada {vname}")
        if parent not in (model["network"].get("ethernets") or {}) and parent not in _live():
            raise ValueError(f"interface pai inexistente: {parent}")
        for existing, c in vlans.items():
            if c.get("link") == parent and int(c.get("id", -1)) == vlan_id:
                raise ValueError(f"VLAN {vlan_id} já existe em {parent} ({existing})")
        cfg: dict[str, Any] = {"id": vlan_id, "link": parent}
        if mtu is not None:
            cfg["mtu"] = mtu
        if ipv4_mode == "dhcp":
            cfg["dhcp4"] = True
        elif ipv4_mode == "static":
            cfg["dhcp4"] = False
            cfg["addresses"] = [address]
            if nameservers:
                cfg["nameservers"] = {"addresses": nameservers}
        else:
            cfg["dhcp4"] = False
        vlans[vname] = cfg
        # Declare the parent only if netplan doesn't know it yet, so we never
        # clobber an existing parent stanza.
        eths = model["network"].setdefault("ethernets", {})
        if parent not in eths:
            eths[parent] = {}
        _apply_model(model)
        if description:
            meta = _load_meta()
            meta.setdefault(vname, {})["description"] = description.strip()[:64]
            _save_meta(meta)
    return get_interface(vname) or {"interface": vname}


def delete_vlan(name: str) -> dict[str, Any]:
    if not VLAN_NAME_RE.match(name) and not IFNAME_RE.match(name):
        raise ValueError("nome de VLAN inválido")
    with _lock:
        model = _load_model(strict=True)
        vlans = model["network"].get("vlans", {})
        if name not in vlans:
            raise ValueError(f"VLAN não encontrada: {name}")
        # Block deletion while a dnsmasq zone still binds to this sub-interface.
        try:
            from . import network as netzones
            if any(z.get("interface") == name for z in netzones.list_zones()):
                raise ValueError(
                    f"a VLAN {name} ainda está em uso por uma zona — remova a zona primeiro")
        except ImportError:
            pass
        del vlans[name]
        _apply_model(model)
        # Tear down the live sub-interface (netplan apply leaves stale links).
        rm = shell.run(["ip", "link", "delete", name], timeout=8)
        meta = _load_meta()
        if meta.pop(name, None) is not None:
            _save_meta(meta)
    warning = None
    # rc 1 with "Cannot find device" just means it was already gone — that's fine.
    if not rm.ok and "Cannot find device" not in rm.stderr:
        warning = f"configuração removida, mas o link ativo persiste: {rm.stderr.strip()}"
    return {"ok": True, "vlan": name, "warning": warning}
