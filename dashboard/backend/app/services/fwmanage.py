"""Managed firewall: pfSense/OPNsense-style rules + NAT, rendered to nftables.

Architecture
------------
A persisted JSON model (aliases, filter rules, port-forwards, outbound NAT) is
rendered into a single managed nft file that *replaces only* the
``inet filter`` and ``ip nat`` tables (the dynamic ``ip mundix_blocklist`` table
is never touched, so live-blocked IPs survive reloads). The base
``/etc/nftables.conf`` includes the managed file so the state is reboot-safe.

Apply flow (crash-safe order): render candidate -> ``nft -c -f`` (validate) ->
``nft -f`` (apply live, atomic) -> atomically commit the managed file ->
ensure include -> persist JSON. If validation/apply fails nothing is committed
and the live ruleset is unchanged (nft transactions are atomic).

Safety: a built-in foundation (loopback, established/related, invalid drop,
ICMP, SSH-always, per-zone DNS/DHCP, rate-limited log+drop) is always emitted
before user rules to avoid lockout. DNAT to management ports (SSH, dashboard
API) is rejected. IP forwarding is surfaced/toggled explicitly, never enabled
silently.
"""
from __future__ import annotations

import contextlib
import contextvars
import ipaddress
import json
import os
import re
import threading
import time
import uuid
from typing import Any

from ..config import settings
from . import shell

# ---------------------------------------------------------------- constants ---

# Interface→zone mapping is NEVER hardcoded: it is derived live from the
# interfaces actually present on the host and the zones the operator has
# configured. This lets the same image run unchanged on any appliance —
# 4 NICs, 6 NICs, different driver names (enpXsY, eth0, igb0…), etc.

# Fallback WAN only used on a brand-new appliance before anything is detected
# or assigned. Real value comes from the persisted model or default-route probe.
_WAN_FALLBACK = ""


def _detect_default_iface() -> str:
    """The interface carrying the host default route — the WAN, detected live."""
    try:
        from . import system
        return system._default_route_iface() or ""
    except Exception:
        return ""


def _wan_iface(model: dict[str, Any] | None = None) -> str:
    """Resolve the WAN interface: operator-pinned value wins, else the live
    default-route interface, else empty (no WAN yet)."""
    if model is None:
        model = load_model()
    pinned = (model.get("wan_iface") or "").strip()
    if pinned:
        return pinned
    return _detect_default_iface() or _WAN_FALLBACK


def _live_zones(wan: str | None = None) -> dict[str, dict[str, str]]:
    """Internal security zones derived from the operator-configured network
    zones (dnsmasq), keyed by zone name → {iface, net}. The WAN interface is
    never treated as an internal zone."""
    if wan is None:
        wan = _wan_iface()
    out: dict[str, dict[str, str]] = {}
    seen_ifaces: set[str] = set()
    try:
        from . import network
        for z in network.list_zones():
            name = z.get("zone")
            iface = z.get("interface")
            net = z.get("network") or ""
            # One internal zone per physical interface; the WAN is never a zone.
            # Deduping by interface prevents nonsensical iif==oif matrix rules.
            if name and iface and iface != wan and iface not in seen_ifaces:
                out[name] = {"iface": iface, "net": net}
                seen_ifaces.add(iface)
    except Exception:
        pass
    return out


def _zone_iface(name: str, zmap: dict[str, dict[str, str]] | None = None,
                wan: str | None = None) -> str:
    """Map a zone name (a configured zone, or 'wan') to its live interface."""
    if wan is None:
        wan = _wan_iface()
    if name == "wan":
        if not wan:
            raise ValueError("interface WAN não definida — configure em Rede › Interfaces")
        return wan
    if zmap is None:
        zmap = _live_zones(wan)
    z = zmap.get(name)
    if not z:
        raise ValueError(f"zona inválida: {name}")
    return z["iface"]


def _default_zone_policies(zone_names: list[str]) -> list[dict[str, Any]]:
    """Secure-by-default inter-zone posture: internal zones are ISOLATED from
    each other (blocked + logged) and may reach the Internet. The operator
    opens specific pairs explicitly via the zone matrix. Works for any number
    of zones with any names."""
    pol: list[dict[str, Any]] = []
    for src in zone_names:
        for dst in zone_names:
            if src != dst:
                pol.append({"src": src, "dst": dst, "action": "block", "log": True})
        pol.append({"src": src, "dst": "wan", "action": "allow", "log": False})
    return pol

MANAGED_FILE = "/etc/nftables.d/mundix-managed.nft"
NFTABLES_CONF = "/etc/nftables.conf"
INCLUDE_LINE = f'include "{MANAGED_FILE}"'
MODEL_PATH = os.path.join(settings.base_dir, "dashboard/backend/data/firewall.json")
SYSCTL_FILE = "/etc/sysctl.d/99-mundix-forward.conf"
IP_FORWARD_PROC = "/proc/sys/net/ipv4/ip_forward"

# Kernel hardening of the network base (anti-spoofing + sane ICMP/redirect
# posture). Persisted as a sysctl.d drop-in so it survives reboot, and applied
# live. rp_filter=2 (loose reverse-path) blocks spoofed sources while staying
# safe for asymmetric/multi-WAN setups; flip to 1 (strict) for single-WAN.
HARDENING_FILE = "/etc/sysctl.d/98-mundix-hardening.conf"
_HARDENING_SYSCTL: dict[str, str] = {
    "net.ipv4.conf.all.rp_filter": "2",
    "net.ipv4.conf.default.rp_filter": "2",
    "net.ipv4.conf.all.accept_source_route": "0",
    "net.ipv4.conf.default.accept_source_route": "0",
    "net.ipv6.conf.all.accept_source_route": "0",
    "net.ipv4.conf.all.accept_redirects": "0",
    "net.ipv4.conf.default.accept_redirects": "0",
    "net.ipv6.conf.all.accept_redirects": "0",
    "net.ipv6.conf.default.accept_redirects": "0",
    "net.ipv4.conf.all.secure_redirects": "0",
    "net.ipv4.conf.default.secure_redirects": "0",
    "net.ipv4.conf.all.send_redirects": "0",
    "net.ipv4.conf.default.send_redirects": "0",
    "net.ipv4.conf.all.log_martians": "1",
    "net.ipv4.conf.default.log_martians": "1",
    "net.ipv4.icmp_echo_ignore_broadcasts": "1",
    "net.ipv4.icmp_ignore_bogus_error_responses": "1",
    "net.ipv4.tcp_syncookies": "1",
}

# Ports that must never be DNAT'd away from the appliance (anti-lockout).
RESERVED_TCP_PORTS = {22, settings.api_port}

_lock = threading.RLock()

_IFACE_RE = re.compile(r"^[a-z][a-z0-9.]{1,14}$")
_ALIAS_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{1,30}$")
_PORT_RE = re.compile(r"^\d{1,5}(-\d{1,5})?$")
_RATE_RE = re.compile(r"^\d{1,7}/(second|minute|hour|day)$")
_LOG_OFF = {"", "0", "none", "unlimited", "off"}

# Default brute-force throttle for new SSH connections arriving on the WAN.
# Generous enough never to hinder a legitimate operator; harsh on scanners.
_SSH_WAN_RATE = "15/minute"

# --------------------------------------------------------------- validation ---


def _vt_ip(v: str) -> str:
    ipaddress.ip_address(v)
    return v


def _vt_net(v: str) -> str:
    ipaddress.ip_network(v, strict=False)
    return v


def _v_host_or_net(v: str) -> str:
    try:
        ipaddress.ip_address(v)
    except ValueError:
        ipaddress.ip_network(v, strict=False)
    return v


def _v_port(v: str) -> str:
    if not _PORT_RE.match(v):
        raise ValueError(f"porta inválida: {v}")
    parts = [int(p) for p in v.split("-")]
    for p in parts:
        if not (0 < p < 65536):
            raise ValueError(f"porta fora do intervalo: {v}")
    if len(parts) == 2 and parts[0] > parts[1]:
        raise ValueError(f"intervalo de portas invertido: {v}")
    return v


def _v_iface(v: str) -> str:
    if not _IFACE_RE.match(v):
        raise ValueError(f"interface inválida: {v}")
    return v


def _v_rate(v: str) -> str:
    """Validate an nftables token-bucket rate like '25/second' or '5/minute'."""
    v = (v or "").strip()
    if not _RATE_RE.match(v):
        raise ValueError(f"taxa inválida (use N/second|minute|hour|day): {v}")
    return v


def _meter_name(prefix: str, rid: str) -> str:
    """Stable, unique nft meter identifier derived from a rule id."""
    rid = re.sub(r"[^a-z0-9]", "", (rid or "x").lower())[:16] or "x"
    return f"mx_{prefix}_{rid}"


# ------------------------------------------------------------------- model ----


def _default_model() -> dict[str, Any]:
    """Seed derived from the LIVE interface/zone reality of this host (not
    hardcoded), so a fresh appliance is configured correctly for whatever
    NICs and zones it actually has."""
    wan = _wan_iface({})
    zmap = _live_zones(wan)
    zone_names = list(zmap.keys())
    snat_rules = [
        {"id": f"seed-snat-{name}", "enabled": True,
         "source_net": z["net"], "oif": wan,
         "description": f"Masquerade {name.upper()}"}
        for name, z in zmap.items() if z.get("net") and wan
    ]
    return {
        "version": 1,
        "wan_iface": "",  # empty = auto-detect via default route
        "aliases": [],
        "filter_rules": [],
        "port_forwards": [],
        "outbound_nat": {"mode": "auto", "rules": snat_rules},
        "zone_policies": _default_zone_policies(zone_names),
    }


def _normalize_zone_policies(existing: list[dict[str, Any]],
                             zone_names: list[str]) -> list[dict[str, Any]]:
    """Rebuild the matrix for the CURRENT set of zones: every expected
    (src,dst) cell exists, operator overrides are preserved, and cells for
    zones that no longer exist are pruned. This keeps the firewall consistent
    as zones are added/removed on different appliances."""
    by_pair = {(c.get("src"), c.get("dst")): c
               for c in existing if c.get("src") and c.get("dst")}
    merged: list[dict[str, Any]] = []
    for d in _default_zone_policies(zone_names):
        cur = by_pair.get((d["src"], d["dst"]))
        merged.append(cur if cur else d)
    return merged


def load_model() -> dict[str, Any]:
    if os.path.isfile(MODEL_PATH):
        try:
            with open(MODEL_PATH) as f:
                data = json.load(f)
            data.setdefault("wan_iface", "")
            data.setdefault("aliases", [])
            data.setdefault("filter_rules", [])
            data.setdefault("port_forwards", [])
            data.setdefault("outbound_nat", {"mode": "auto", "rules": []})
            # Egress is now governed by the inter-zone matrix; drop the legacy
            # seed forward accepts so a WAN "block" cell isn't pre-empted.
            data["filter_rules"] = [
                r for r in data["filter_rules"]
                if r.get("id") not in ("seed-lan-wan", "seed-dmz-wan")
            ]
            wan = _wan_iface(data)
            zone_names = list(_live_zones(wan).keys())
            data["zone_policies"] = _normalize_zone_policies(
                data.get("zone_policies") or [], zone_names)
            return data
        except (json.JSONDecodeError, OSError):
            pass
    return _default_model()


def _save_model(model: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    _atomic_write(MODEL_PATH, json.dumps(model, indent=2, ensure_ascii=False))


def _atomic_write(path: str, content: str, mode: int = 0o644) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}.{int(time.time()*1000)}"
    with open(tmp, "w") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, mode)
    os.replace(tmp, path)


# ---------------------------------------------------------------- aliases -----


def _alias_map(model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {a["name"]: a for a in model.get("aliases", [])}


def _dedup(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in seq:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _collect_alias_addrs(name: str, amap: dict[str, dict[str, Any]],
                         path: tuple[str, ...] = ()) -> list[str]:
    """Recursively flatten an address alias (host/network/group) into raw nft
    address values. Cycle detection is scoped to group names; leaf hosts/networks
    may be referenced through multiple branches (diamond) without error."""
    a = amap.get(name)
    if not a:
        raise ValueError(f"alias inexistente: {name}")
    t = a.get("type")
    if t in ("host", "network"):
        return list(a.get("values") or [])
    if t == "group":
        if name in path:
            raise ValueError(f"referência circular de alias de grupo: {name}")
        path = path + (name,)
        out: list[str] = []
        for member in (a.get("values") or []):
            out.extend(_collect_alias_addrs(member, amap, path))
        return out
    raise ValueError(f"alias '{name}' não é de endereço (host/rede/grupo)")


def _resolve_addr(token: str, amap: dict[str, dict[str, Any]]) -> str:
    """Resolve a source/dest token into an nft address match value."""
    token = (token or "any").strip()
    if token in ("", "any"):
        return ""
    if token.startswith("alias:"):
        name = token[6:]
        vals = _dedup(_collect_alias_addrs(name, amap))
        if not vals:
            raise ValueError(f"alias '{name}' não possui valores")
        if len(vals) == 1:
            return vals[0]
        return "{ " + ", ".join(vals) + " }"
    return _v_host_or_net(token)


def _v_addr_token(token: str, amap: dict[str, dict[str, Any]],
                  *, allow_any: bool = True) -> str:
    """Validate an address token that may be a literal host/network or an
    alias:NAME reference (host/network/group). Resolution is deferred to render."""
    token = (token or "").strip()
    if token in ("", "any"):
        if allow_any:
            return token
        raise ValueError("endereço obrigatório")
    if token.startswith("alias:"):
        name = token[6:]
        a = amap.get(name)
        if not a or a.get("type") not in ("host", "network", "group"):
            raise ValueError(f"alias de endereço inexistente: {name}")
        return token
    return _v_host_or_net(token)


def _resolve_port(token: str, amap: dict[str, dict[str, Any]]) -> str:
    token = (token or "").strip()
    if token == "":
        return ""
    if token.startswith("alias:"):
        name = token[6:]
        a = amap.get(name)
        if not a or a["type"] != "port":
            raise ValueError(f"alias de porta inexistente: {name}")
        vals = a["values"]
        if len(vals) == 1:
            return vals[0]
        return "{ " + ", ".join(vals) + " }"
    return _v_port(token)


# ------------------------------------------------------------------ render ----


def _render_filter_rule(r: dict[str, Any], amap: dict[str, dict[str, Any]]) -> str:
    """Render a managed filter rule, possibly as MULTIPLE nft lines:
      1. an optional non-terminal log line (so logging never alters the verdict —
         this is what makes logging on an `accept` rule behave correctly);
      2. an optional per-source connection-count guard (drops NEW connections from
         a source over the limit);
      3. the main verdict line, with an optional per-source rate-limit meter
         (packets over the rate fall through to the chain's default policy).
    All conditional matches are repeated on each line so they bind to the same
    traffic selector."""
    match: list[str] = []
    if r.get("iif"):
        match.append(f'iifname "{_v_iface(r["iif"])}"')
    if r.get("oif") and r.get("chain") == "forward":
        match.append(f'oifname "{_v_iface(r["oif"])}"')
    saddr = _resolve_addr(r.get("source", "any"), amap)
    if saddr:
        match.append(f"ip saddr {saddr}")
    daddr = _resolve_addr(r.get("dest", "any"), amap)
    if daddr:
        match.append(f"ip daddr {daddr}")
    proto = r.get("proto", "any")
    dport = _resolve_port(r.get("dport", ""), amap)
    if proto in ("tcp", "udp"):
        if dport:
            match.append(f"{proto} dport {dport}")
        else:
            match.append(f"meta l4proto {proto}")
    elif proto == "icmp":
        match.append("ip protocol icmp")
    elif dport:
        raise ValueError("porta exige protocolo tcp ou udp")

    action = r.get("action", "accept")
    if action not in ("accept", "drop", "reject"):
        raise ValueError(f"ação inválida: {action}")
    rid = r.get("id", "")
    lines: list[str] = []

    if r.get("log"):
        safe = re.sub(r"[^A-Za-z0-9 _-]", "", (r.get("description") or "rule"))[:24]
        log_parts = list(match)
        lr = str(r.get("log_rate") or "5/minute").strip()
        if lr.lower() in _LOG_OFF:
            log_parts.append(f'log prefix "MX-RULE {safe}: "')
        else:
            _v_rate(lr)
            log_parts.append(f'limit rate {lr} log prefix "MX-RULE {safe}: "')
        lines.append("        " + " ".join(log_parts))

    conn = r.get("conn_limit")
    if conn not in (None, "", 0):
        n = int(conn)
        if n <= 0:
            raise ValueError("limite de conexões deve ser > 0")
        cl_parts = list(match)
        cl_parts.append(
            f"ct state new meter {_meter_name('cl', rid)} "
            f"{{ ip saddr ct count over {n} }} drop")
        lines.append("        " + " ".join(cl_parts))

    main_parts = list(match)
    rate = r.get("rate_limit")
    if rate:
        rl = _v_rate(str(rate))
        main_parts.append(
            f"meter {_meter_name('rl', rid)} {{ ip saddr limit rate {rl} }}")
    main_parts.append(action)
    lines.append("        " + " ".join(main_parts))
    return "\n".join(lines)


def _render_dnat(pf: dict[str, Any], amap: dict[str, dict[str, Any]],
                 wan: str = "") -> str:
    iif = _v_iface(pf.get("iif") or wan or _wan_iface())
    proto = pf["proto"]
    if proto not in ("tcp", "udp"):
        raise ValueError("port-forward exige tcp ou udp")
    dport = _v_port(str(pf["dport"]))
    to_ip = _vt_ip(pf["to_ip"])
    to_port = str(pf.get("to_port") or pf["dport"])
    _v_port(to_port)
    parts = [f'iifname "{iif}"']
    saddr = _resolve_addr(pf.get("source", "any"), amap)
    if saddr:
        parts.append(f"ip saddr {saddr}")
    parts.append(f"{proto} dport {dport}")
    parts.append(f"dnat to {to_ip}:{to_port}")
    return "        " + " ".join(parts)


def _render_pf_forward_accept(pf: dict[str, Any],
                              amap: dict[str, dict[str, Any]],
                              wan: str = "") -> str:
    iif = _v_iface(pf.get("iif") or wan or _wan_iface())
    proto = pf["proto"]
    to_ip = _vt_ip(pf["to_ip"])
    to_port = str(pf.get("to_port") or pf["dport"])
    parts = ["ct status dnat", f'iifname "{iif}"', f"ip daddr {to_ip}",
             f"{proto} dport {to_port}"]
    saddr = _resolve_addr(pf.get("source", "any"), amap)
    if saddr:
        parts.append(f"ip saddr {saddr}")
    parts.append("accept")
    return "        " + " ".join(parts)


def _render_zone_policy(c: dict[str, Any], zmap: dict[str, dict[str, str]],
                        wan: str) -> str:
    """Render one inter-zone matrix cell as an explicit forward rule. Allow ->
    accept, block -> drop (optionally rate-limited log). Matching on interfaces
    is what binds the rule to a zone pair."""
    iif = _zone_iface(c["src"], zmap, wan)
    oif = _zone_iface(c["dst"], zmap, wan)
    action = "accept" if c.get("action") == "allow" else "drop"
    parts = [f'iifname "{iif}"', f'oifname "{oif}"']
    if action == "drop" and c.get("log"):
        parts.append(
            f'limit rate 5/minute log prefix "MX-ZONE {c["src"]}>{c["dst"]}: "')
    parts.append(action)
    return "        " + " ".join(parts)


def render(model: dict[str, Any]) -> str:
    amap = _alias_map(model)
    rules = sorted(model.get("filter_rules", []), key=lambda r: r.get("order", 0))
    in_rules = [r for r in rules if r.get("chain") == "input" and r.get("enabled", True)]
    fw_rules = [r for r in rules if r.get("chain") == "forward" and r.get("enabled", True)]
    pfs = [p for p in model.get("port_forwards", []) if p.get("enabled", True)]
    snat = model.get("outbound_nat", {})
    snat_rules = [s for s in snat.get("rules", []) if s.get("enabled", True)]

    # Live interface/zone context — adapts to whatever this appliance has.
    wan = _wan_iface(model)
    zmap = _live_zones(wan)
    zone_ifaces = [z["iface"] for z in zmap.values()]
    zones_set = ("{ " + ", ".join(f'"{i}"' for i in zone_ifaces) + " }") if zone_ifaces else ""
    L: list[str] = []
    a = L.append
    a("#!/usr/sbin/nft -f")
    a("# AUTO-GERADO pelo Mundix360. Não edite à mão — use o dashboard.")
    a("")
    a("table inet filter")
    a("delete table inet filter")
    a("table inet filter {")
    a("    chain input {")
    a("        type filter hook input priority 0; policy drop;")
    a('        iifname "lo" accept')
    a("        ct state established,related accept")
    a("        ct state invalid drop")
    a("        ip protocol icmp icmp type { echo-request, echo-reply, "
      "destination-unreachable, time-exceeded } accept")
    # IPv6 ICMP (Neighbour Discovery, RA, PMTUD) is REQUIRED — without this,
    # the policy-drop inet table silently breaks all IPv6 the moment it is
    # enabled on any interface. Kept always-on so the box is v6-safe-by-default.
    a("        ip6 nexthdr ipv6-icmp accept")
    # SSH management: internal zones unrestricted; from WAN, throttle *new*
    # connections to blunt brute-force. Established sessions are accepted
    # above, so the operator is never locked out of an active session.
    ssh_rate = (model.get("ssh_wan_rate") or _SSH_WAN_RATE).strip()
    if wan:
        wan_if = _v_iface(wan)
        # Per-source meter: each source IP gets its own budget, so a scanner
        # flooding SSH can never exhaust the operator's allowance.
        a(f'        iifname "{wan_if}" tcp dport 22 ct state new meter mx_ssh_wan '
          f'{{ ip saddr limit rate {ssh_rate} burst 5 packets }} accept')
        a(f'        iifname "{wan_if}" tcp dport 22 ct state new '
          'log prefix "NFT-SSH-THROTTLE: " drop')
    a("        tcp dport 22 accept")
    if zones_set:
        a(f"        iifname {zones_set} udp dport 53 accept")
        a(f"        iifname {zones_set} tcp dport 53 accept")
        a(f"        iifname {zones_set} udp sport 68 udp dport 67 accept")
    for r in in_rules:
        a(_render_filter_rule(r, amap))
    a('        limit rate 5/minute log prefix "NFT-INPUT-DROP: " drop')
    a("    }")
    a("    chain forward {")
    a("        type filter hook forward priority 0; policy drop;")
    a("        ct state established,related accept")
    a("        ct state invalid drop")
    for pf in pfs:
        a(_render_pf_forward_accept(pf, amap, wan))
    for r in fw_rules:
        a(_render_filter_rule(r, amap))
    a("        # --- inter-zone baseline (managed matrix) ---")
    for cell in model.get("zone_policies", []):
        # Without a resolvable WAN (e.g. fresh appliance, no default route yet)
        # skip cells that reference 'wan' so render never fails — the box stays
        # manageable until the operator assigns a WAN.
        if not wan and "wan" in (cell.get("src"), cell.get("dst")):
            continue
        a(_render_zone_policy(cell, zmap, wan))
    a("        ip protocol icmp accept")
    a("        ip6 nexthdr ipv6-icmp accept")
    a('        limit rate 5/minute log prefix "NFT-FORWARD-DROP: " drop')
    a("    }")
    a("    chain output {")
    a("        type filter hook output priority 0; policy accept;")
    a("    }")
    a("}")
    a("")
    a("table ip nat")
    a("delete table ip nat")
    a("table ip nat {")
    a("    chain prerouting {")
    a("        type nat hook prerouting priority -100; policy accept;")
    for pf in pfs:
        a(_render_dnat(pf, amap, wan))
    a("    }")
    a("    chain postrouting {")
    a("        type nat hook postrouting priority 100; policy accept;")
    for s in snat_rules:
        out_if = s.get("oif") or wan
        if not out_if:
            # No outbound interface (WAN not assigned yet) — skip masquerade
            # rather than emit an invalid rule.
            continue
        oif = _v_iface(out_if)
        net = _resolve_addr(s["source_net"], amap)
        if not net:
            raise ValueError("NAT de saída exige rede/alias de origem")
        a(f'        oifname "{oif}" ip saddr {net} masquerade')
    a("    }")
    a("}")
    a("")
    return "\n".join(L)


# ------------------------------------------------------------------- apply ----


def _ensure_include() -> None:
    try:
        with open(NFTABLES_CONF) as f:
            content = f.read()
    except OSError:
        return
    if INCLUDE_LINE in content:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += f"\n# Mundix360 managed ruleset\n{INCLUDE_LINE}\n"
    _atomic_write(NFTABLES_CONF, content, mode=0o755)


def _commit_nft(content: str) -> None:
    """Validate (nft -c), apply live (nft -f, atomic) and commit the managed
    file. Raises ValueError on validation failure, RuntimeError on apply."""
    candidate = MANAGED_FILE + ".candidate"
    os.makedirs(os.path.dirname(MANAGED_FILE), exist_ok=True)
    _atomic_write(candidate, content)
    try:
        chk = shell.run(["nft", "-c", "-f", candidate], timeout=15)
        if not chk.ok:
            raise ValueError(f"validação nft falhou: {chk.stderr.strip()}")
        ap = shell.run(["nft", "-f", candidate], timeout=15)
        if not ap.ok:
            raise RuntimeError(f"aplicação nft falhou: {ap.stderr.strip()}")
        os.replace(candidate, MANAGED_FILE)
        _ensure_include()
    finally:
        if os.path.exists(candidate):
            try:
                os.remove(candidate)
            except OSError:
                pass


# --- confirm-or-revert (anti-lockout for risky changes) ----------------------
# After a guarded apply we keep a snapshot of the previous live ruleset + model.
# Unless the operator confirms connectivity within the window, the firewall
# auto-reverts — mirroring `netplan try`. Protects against a valid-but-locking
# ruleset (e.g. a rule that cuts the operator's own management path).

_pending: dict[str, Any] | None = None

# Per-request "arming" of the confirm-or-revert window. The router sets this for
# lockout-prone mutations; _mutate reads it so any guarded change can auto-revert
# without threading the parameter through every CRUD signature.
_revert_ctx: contextvars.ContextVar[int] = contextvars.ContextVar(
    "fw_revert_after", default=0)


@contextlib.contextmanager
def arm_revert(seconds: int):
    """Context manager: arm auto-revert for mutations made inside the block."""
    tok = _revert_ctx.set(int(seconds or 0))
    try:
        yield
    finally:
        _revert_ctx.reset(tok)


def _read_managed() -> str | None:
    try:
        with open(MANAGED_FILE) as f:
            return f.read()
    except OSError:
        return None


def _auto_revert(token: str) -> None:
    global _pending
    with _lock:
        if not _pending or _pending.get("token") != token:
            return
        prev_content = _pending.get("prev_content")
        prev_model = _pending.get("prev_model")
        try:
            # prev_content is guaranteed non-None (apply_model only arms when a
            # known-good previous ruleset exists), so this restores live nft to
            # the last confirmed state atomically.
            _commit_nft(prev_content)
            if prev_model is not None:
                _save_model(prev_model)
            _pending = None
        except Exception:
            # Restore failed — do NOT pretend the change was reverted. Keep an
            # error marker so /pending surfaces the inconsistency to the operator.
            import logging
            logging.getLogger(__name__).critical(
                "auto-revert do firewall FALHOU — ruleset pode estar inconsistente",
                exc_info=True)
            _pending = {**_pending, "timer": None, "error": True}


def pending_status() -> dict[str, Any]:
    with _lock:
        if not _pending:
            return {"pending": False}
        if _pending.get("error"):
            return {"pending": True, "error": True, "token": _pending["token"],
                    "seconds_left": 0,
                    "message": "Falha ao reverter — verifique o ruleset."}
        left = max(0, int(_pending["deadline"] - time.time()))
        return {"pending": True, "token": _pending["token"],
                "seconds_left": left}


def confirm_pending(token: str) -> dict[str, Any]:
    """Confirm a guarded apply, cancelling the scheduled auto-revert."""
    global _pending
    with _lock:
        if not _pending or _pending.get("token") != token:
            raise ValueError("nenhuma alteração pendente com este token")
        timer = _pending.get("timer")
        if timer:
            timer.cancel()
        _pending = None
    return {"ok": True, "confirmed": True}


def apply_model(model: dict[str, Any], *, persist: bool = True,
                revert_after: int = 0) -> dict[str, Any]:
    """Validate, apply live (atomic), commit the managed file, persist JSON.

    If ``revert_after`` (seconds) > 0, snapshot the previous ruleset/model and
    schedule an auto-revert unless ``confirm_pending(token)`` is called first.
    """
    global _pending
    with _lock:
        prev_content = _read_managed() if revert_after > 0 else None
        prev_model = load_model() if revert_after > 0 else None
        _commit_nft(render(model))
        if persist:
            _save_model(model)
        result = {"ok": True, "applied": True}
        # Only arm auto-revert when we captured a known-good previous ruleset to
        # restore to. Without it (e.g. very first apply, no managed file yet) we
        # cannot cleanly roll back, so we don't make a false safety promise.
        if revert_after > 0 and prev_content is not None:
            # A previous unconfirmed pending change is implicitly confirmed:
            # the operator is clearly still reachable to issue this new one.
            if _pending and _pending.get("timer"):
                _pending["timer"].cancel()
            token = uuid.uuid4().hex
            timer = threading.Timer(revert_after, _auto_revert, args=(token,))
            timer.daemon = True
            timer.start()
            _pending = {"token": token, "timer": timer,
                        "prev_content": prev_content, "prev_model": prev_model,
                        "deadline": time.time() + revert_after}
            result.update({"pending": True, "token": token,
                           "revert_after": revert_after})
    return result


# ---------------------------------------------------------------- CRUD ops ----


def _mutate(fn) -> dict[str, Any]:
    with _lock:
        model = load_model()
        fn(model)
        apply_model(model, revert_after=_revert_ctx.get())
        return model


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# filter rules ----------------------------------------------------------------

def list_rules() -> list[dict[str, Any]]:
    rules = load_model().get("filter_rules", [])
    return sorted(rules, key=lambda r: r.get("order", 0))


def save_rule(rule: dict[str, Any]) -> dict[str, Any]:
    def op(model):
        rules = model["filter_rules"]
        rid = rule.get("id")
        if rid:
            for i, r in enumerate(rules):
                if r["id"] == rid:
                    rules[i] = {**r, **rule}
                    return
        rule["id"] = _new_id()
        if "order" not in rule or rule["order"] is None:
            rule["order"] = (max((r.get("order", 0) for r in rules), default=0) + 10)
        rules.append(rule)
    return _mutate(op)


def delete_rule(rid: str) -> dict[str, Any]:
    def op(model):
        model["filter_rules"] = [r for r in model["filter_rules"] if r["id"] != rid]
    return _mutate(op)


def move_rule(rid: str, direction: str) -> dict[str, Any]:
    def op(model):
        rules = sorted(model["filter_rules"], key=lambda r: r.get("order", 0))
        idx = next((i for i, r in enumerate(rules) if r["id"] == rid), None)
        if idx is None:
            raise ValueError("regra não encontrada")
        swap = idx - 1 if direction == "up" else idx + 1
        # only swap within the same chain
        chain = rules[idx]["chain"]
        while 0 <= swap < len(rules) and rules[swap]["chain"] != chain:
            swap += -1 if direction == "up" else 1
        if not (0 <= swap < len(rules)):
            return
        rules[idx]["order"], rules[swap]["order"] = (
            rules[swap].get("order", 0), rules[idx].get("order", 0))
    return _mutate(op)


# port forwards ---------------------------------------------------------------

def list_port_forwards() -> list[dict[str, Any]]:
    return load_model().get("port_forwards", [])


def _check_pf(pf: dict[str, Any]) -> None:
    proto = pf.get("proto")
    if proto not in ("tcp", "udp"):
        raise ValueError("protocolo deve ser tcp ou udp")
    dport = str(pf.get("dport", ""))
    _v_port(dport)
    # anti-lockout: never DNAT the appliance management ports on WAN
    if proto == "tcp" and "-" not in dport and int(dport) in RESERVED_TCP_PORTS:
        raise ValueError(
            f"porta {dport} é reservada para gestão do appliance (SSH/API) "
            "e não pode ser redirecionada")
    _vt_ip(pf["to_ip"])
    if pf.get("to_port"):
        _v_port(str(pf["to_port"]))


def save_port_forward(pf: dict[str, Any]) -> dict[str, Any]:
    _check_pf(pf)
    def op(model):
        pfs = model["port_forwards"]
        pid = pf.get("id")
        if pid:
            for i, p in enumerate(pfs):
                if p["id"] == pid:
                    pfs[i] = {**p, **pf}
                    return
        pf["id"] = _new_id()
        pfs.append(pf)
    return _mutate(op)


def delete_port_forward(pid: str) -> dict[str, Any]:
    def op(model):
        model["port_forwards"] = [p for p in model["port_forwards"] if p["id"] != pid]
    return _mutate(op)


# inter-zone policies (matrix) -----------------------------------------------

def list_zone_policies() -> dict[str, Any]:
    """Return the LIVE zone catalog plus the current inter-zone matrix as
    cells. Zones are derived from the appliance's configured network zones, so
    the matrix adapts automatically to whatever exists."""
    model = load_model()
    wan = _wan_iface(model)
    zmap = _live_zones(wan)
    zones = [{"name": n, "iface": z["iface"], "net": z["net"]}
             for n, z in zmap.items()]
    zone_names = list(zmap.keys())
    return {
        "wan_iface": wan,
        "zones": zones,
        "dst_zones": zone_names + ["wan"],
        "policies": model.get("zone_policies", []),
    }


def set_zone_policy(src: str, dst: str, action: str,
                    log: bool = True) -> dict[str, Any]:
    """Upsert a single matrix cell. src must be an internal zone; dst may be an
    internal zone or 'wan'. src may not equal dst."""
    zone_names = list(_live_zones().keys())
    if src not in zone_names:
        raise ValueError(f"zona de origem inválida: {src}")
    if dst not in zone_names and dst != "wan":
        raise ValueError(f"zona de destino inválida: {dst}")
    if src == dst:
        raise ValueError("origem e destino não podem ser a mesma zona")
    if action not in ("allow", "block"):
        raise ValueError("ação deve ser allow ou block")

    def op(model: dict[str, Any]) -> None:
        pols = model.setdefault("zone_policies", [])
        for cell in pols:
            if cell.get("src") == src and cell.get("dst") == dst:
                cell["action"] = action
                cell["log"] = bool(log)
                break
        else:
            pols.append({"src": src, "dst": dst,
                         "action": action, "log": bool(log)})

    return _mutate(op)


# WAN / interface assignment --------------------------------------------------

def get_wan() -> str:
    """The currently effective WAN interface (pinned or auto-detected)."""
    return _wan_iface()


def set_wan(iface: str) -> dict[str, Any]:
    """Pin the WAN interface. Empty string restores auto-detection. The
    interface must actually exist on this host. Re-renders the firewall so all
    NAT/zone rules immediately track the new WAN."""
    iface = (iface or "").strip()
    if iface:
        if not _IFACE_RE.match(iface):
            raise ValueError(f"interface inválida: {iface}")
        try:
            from . import system
            present = {i["interface"] for i in system.interfaces()}
        except Exception:
            present = set()
        if present and iface not in present:
            raise ValueError(f"interface inexistente neste appliance: {iface}")

    def op(model: dict[str, Any]) -> None:
        model["wan_iface"] = iface
        wan = _wan_iface(model)
        zmap = _live_zones(wan)
        # Rebuild auto seed SNAT (masquerade) for the new topology: keep any
        # manual/non-seed NAT rules, regenerate one masquerade per live zone.
        nat = model.setdefault("outbound_nat", {"mode": "auto", "rules": []})
        manual = [s for s in nat.get("rules", [])
                  if not str(s.get("id", "")).startswith("seed-snat-")]
        seeds = [
            {"id": f"seed-snat-{name}", "enabled": True,
             "source_net": z["net"], "oif": wan,
             "description": f"Masquerade {name.upper()}"}
            for name, z in zmap.items() if z.get("net") and wan
        ]
        nat["rules"] = seeds + manual
        # Prune/extend the inter-zone matrix to the new set of zones.
        model["zone_policies"] = _normalize_zone_policies(
            model.get("zone_policies", []), list(zmap.keys()))

    return _mutate(op)


def interface_assignments() -> dict[str, Any]:
    """Professional overview of every detected NIC and the role it plays:
    WAN, a named internal zone, or unassigned. Fully adaptive — reflects the
    real hardware of whatever appliance this runs on."""
    try:
        from . import system
        ifaces = system.interfaces()
    except Exception:
        ifaces = []
    wan = _wan_iface()
    zmap = _live_zones(wan)
    iface_to_zone = {z["iface"]: name for name, z in zmap.items()}

    rows = []
    for i in ifaces:
        name = i.get("interface")
        if name == wan:
            role, zone = "wan", None
        elif name in iface_to_zone:
            role, zone = "zone", iface_to_zone[name]
        else:
            role, zone = "unassigned", None
        rows.append({**i, "role": role, "zone": zone})
    return {
        "wan_iface": wan,
        "wan_pinned": bool((load_model().get("wan_iface") or "").strip()),
        "interfaces": rows,
        "zones": [{"name": n, "iface": z["iface"], "net": z["net"]}
                  for n, z in zmap.items()],
    }


# aliases ---------------------------------------------------------------------

def list_aliases() -> list[dict[str, Any]]:
    return load_model().get("aliases", [])


def _check_alias(al: dict[str, Any]) -> None:
    if not _ALIAS_RE.match(al.get("name", "")):
        raise ValueError("nome de alias inválido (letras/números/_)")
    t = al.get("type")
    if t not in ("host", "network", "port", "group"):
        raise ValueError("tipo deve ser host, network, port ou group")
    vals = al.get("values") or []
    if not vals:
        raise ValueError("alias precisa de ao menos um valor")
    for v in vals:
        if t == "host":
            _vt_ip(v)
        elif t == "network":
            _vt_net(v)
        elif t == "port":
            _v_port(v)
        else:  # group: members are alias names (resolved/validated later)
            if not _ALIAS_RE.match(v):
                raise ValueError(f"membro de grupo inválido: {v}")
            if v == al.get("name"):
                raise ValueError("grupo não pode referenciar a si mesmo")


def save_alias(al: dict[str, Any]) -> dict[str, Any]:
    _check_alias(al)
    def op(model):
        aliases = model["aliases"]
        aid = al.get("id")
        if aid:
            for i, a in enumerate(aliases):
                if a["id"] == aid:
                    aliases[i] = {**a, **al}
                    break
            else:
                raise ValueError("alias não encontrado")
        else:
            if any(a["name"] == al["name"] for a in aliases):
                raise ValueError(f"alias '{al['name']}' já existe")
            al["id"] = _new_id()
            aliases.append(al)
        # Deep-validate every group alias against the resulting model so that
        # missing references and circular groups are rejected atomically.
        amap = _alias_map(model)
        for a in aliases:
            if a.get("type") == "group":
                addrs = _collect_alias_addrs(a["name"], amap)
                if not addrs:
                    raise ValueError(f"grupo '{a['name']}' não resolve endereços")
    return _mutate(op)


def delete_alias(aid: str) -> dict[str, Any]:
    def op(model):
        target = next((a for a in model["aliases"] if a["id"] == aid), None)
        if target:
            name = target["name"]
            ref = f"alias:{name}"
            used_rule = any(
                ref in (r.get("source"), r.get("dest"), r.get("dport"))
                for r in model.get("filter_rules", []))
            used_pf = any(
                ref == (p.get("source") or "")
                for p in model.get("port_forwards", []))
            used_snat = any(
                ref == (s.get("source_net") or "")
                for s in model.get("outbound_nat", {}).get("rules", []))
            used_group = any(
                a.get("type") == "group" and name in (a.get("values") or [])
                for a in model["aliases"])
            if used_rule or used_pf or used_snat or used_group:
                raise ValueError(
                    f"alias '{name}' está em uso (regra/PF/NAT/grupo)")
        model["aliases"] = [a for a in model["aliases"] if a["id"] != aid]
    return _mutate(op)


# outbound nat ----------------------------------------------------------------

def get_outbound() -> dict[str, Any]:
    return load_model().get("outbound_nat", {"mode": "auto", "rules": []})


def set_outbound(data: dict[str, Any]) -> dict[str, Any]:
    mode = data.get("mode", "auto")
    if mode not in ("auto", "manual"):
        raise ValueError("modo deve ser auto ou manual")
    amap = _alias_map(load_model())
    for s in data.get("rules", []):
        _v_addr_token(s["source_net"], amap, allow_any=False)
        _v_iface(s.get("oif") or _wan_iface())
    def op(model):
        for s in data.get("rules", []):
            s.setdefault("id", _new_id())
            s.setdefault("enabled", True)
        model["outbound_nat"] = {"mode": mode, "rules": data.get("rules", [])}
    return _mutate(op)


# ---------------------------------------------------------------- hardening ---

def get_hardening() -> dict[str, Any]:
    """Live + persisted state of the kernel network-hardening posture."""
    live: dict[str, str] = {}
    for key in _HARDENING_SYSCTL:
        proc = "/proc/sys/" + key.replace(".", "/")
        try:
            with open(proc) as f:
                live[key] = f.read().strip()
        except OSError:
            live[key] = ""
    applied = all(live.get(k) == v for k, v in _HARDENING_SYSCTL.items())
    return {
        "persisted": os.path.isfile(HARDENING_FILE),
        "applied": applied,
        "desired": dict(_HARDENING_SYSCTL),
        "live": live,
    }


def apply_hardening() -> dict[str, Any]:
    """Persist the hardening drop-in and apply it live. Idempotent."""
    with _lock:
        body = ("# AUTO-GERADO pelo Mundix360 — hardening de rede. Não edite à mão.\n"
                + "".join(f"{k} = {v}\n" for k, v in _HARDENING_SYSCTL.items()))
        _atomic_write(HARDENING_FILE, body)
        res = shell.run(["sysctl", "-p", HARDENING_FILE], timeout=15)
        if not res.ok:
            raise RuntimeError(f"sysctl falhou: {res.stderr.strip()}")
    return get_hardening()


# ---------------------------------------------------------- forwarding/sysctl --

def get_forwarding() -> dict[str, Any]:
    live = None
    try:
        with open(IP_FORWARD_PROC) as f:
            live = f.read().strip() == "1"
    except OSError:
        pass
    persisted = os.path.isfile(SYSCTL_FILE)
    return {"enabled": bool(live), "persisted": persisted,
            "required_by_nat": True}


def set_forwarding(enabled: bool) -> dict[str, Any]:
    with _lock:
        try:
            with open(IP_FORWARD_PROC, "w") as f:
                f.write("1\n" if enabled else "0\n")
        except OSError as e:
            raise RuntimeError(f"não foi possível ajustar ip_forward: {e}")
        if enabled:
            _atomic_write(SYSCTL_FILE, "net.ipv4.ip_forward = 1\n")
        elif os.path.isfile(SYSCTL_FILE):
            try:
                os.remove(SYSCTL_FILE)
            except OSError:
                pass
    return get_forwarding()


# --------------------------------------------------------------- overview -----

def overview() -> dict[str, Any]:
    model = load_model()
    return {
        "filter_rules": len(model.get("filter_rules", [])),
        "input_rules": sum(1 for r in model.get("filter_rules", [])
                           if r.get("chain") == "input"),
        "forward_rules": sum(1 for r in model.get("filter_rules", [])
                             if r.get("chain") == "forward"),
        "port_forwards": len(model.get("port_forwards", [])),
        "aliases": len(model.get("aliases", [])),
        "zone_policies": len(model.get("zone_policies", [])),
        "zone_blocks": sum(1 for c in model.get("zone_policies", [])
                           if c.get("action") == "block"),
        "outbound_mode": model.get("outbound_nat", {}).get("mode", "auto"),
        "managed_active": os.path.isfile(MANAGED_FILE),
        "include_installed": _include_present(),
        "forwarding": get_forwarding(),
        "hardening": get_hardening(),
    }


def _include_present() -> bool:
    try:
        with open(NFTABLES_CONF) as f:
            return INCLUDE_LINE in f.read()
    except OSError:
        return False
