"""Multi-WAN: failover + load-balancing across 2-3 internet links.

Why this exists
---------------
In Brazil it is common (and often essential) to have 2-3 ISP links because any
single connection oscillates. netplan alone cannot do this: the kernel keeps a
configured default route even when the *link is up but the Internet is down* —
exactly the failure that matters here. So we add an active layer:

  * a health monitor that pings a per-link monitor IP *through each interface*,
  * a router that installs/swaps the default route (failover) or an ECMP
    weighted multipath route (load-balance) based on which links are alive,
  * per-link source-routing tables so the appliance's own replies stay
    symmetric (a packet that arrived via WAN2 replies via WAN2),
  * a dedicated nftables NAT table that masquerades out every WAN member.

Design guarantees
-----------------
* **Opt-in, OFF by default.** When disabled this module touches nothing — the
  appliance behaves exactly as a single-WAN box managed by netplan/fwmanage.
* **Never strand the box.** The router never deletes the last default route
  leaving the appliance offline; if every monitor is down it still installs the
  highest-priority gateway so connectivity can recover on its own.
* **Self-asserting.** The monitor re-applies routing every tick, so a
  `netplan apply` (which would reinstall the static default) is corrected
  automatically within one interval.
* **Isolated.** State lives in /etc/mundix/multiwan.json; the NAT lives in its
  own `ip mundix_mwan` table — fwmanage's managed tables are never touched.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import threading
import time
from typing import Any

from . import shell

MODEL_PATH = "/etc/mundix/multiwan.json"
MWAN_NFT_TABLE = "mundix_mwan"
# ip-rule priority band and routing-table id base we own exclusively.
_RULE_PRIO_BASE = 11000
_TABLE_ID_BASE = 200
_MAX_SLOTS = 64  # fixed owned band; cleared fully so reconfigure never leaks

_lock = threading.RLock()
_health: dict[str, dict[str, Any]] = {}
_monitor_thread: threading.Thread | None = None
_monitor_stop = threading.Event()

_IFACE_RE = re.compile(r"^[a-z][a-z0-9.]{1,14}$")


# ----------------------------------------------------------------- model -----

def _default_model() -> dict[str, Any]:
    return {
        "enabled": False,
        "mode": "failover",          # failover | loadbalance
        "interval": 10,              # seconds between health checks
        "down_after": 3,             # consecutive failures to mark a gw down
        "up_after": 2,               # consecutive successes to mark it up
        "gateways": [],              # see _norm_gateway
    }


def _norm_gateway(g: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": g.get("id") or os.urandom(4).hex(),
        "name": (g.get("name") or g.get("iface") or "wan").strip(),
        "iface": g["iface"],
        "gateway": (g.get("gateway") or "auto").strip(),   # 'auto' or an IP
        "monitor_ip": (g.get("monitor_ip") or "8.8.8.8").strip(),
        "weight": int(g.get("weight") or 1),
        "tier": int(g.get("tier") or 1),                   # lower = preferred
        "enabled": bool(g.get("enabled", True)),
    }


def load_model() -> dict[str, Any]:
    try:
        with open(MODEL_PATH) as f:
            m = json.load(f)
    except (OSError, ValueError):
        return _default_model()
    base = _default_model()
    base.update({k: m[k] for k in base if k in m})
    base["gateways"] = [_norm_gateway(g) for g in m.get("gateways", []) if g.get("iface")]
    return base


def _save_model(model: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    tmp = MODEL_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(model, f, indent=2)
    os.replace(tmp, MODEL_PATH)


# ------------------------------------------------------ live resolution ------

def _v_iface(v: str) -> str:
    if not _IFACE_RE.match(v or ""):
        raise ValueError(f"interface inválida: {v}")
    return v


def _resolve_gateway(iface: str) -> str | None:
    """Resolve a link's gateway: the explicit default 'via' on that interface
    (static or DHCP-assigned). Returns None if none is known yet."""
    r = shell.run(["ip", "-o", "route", "show", "default", "dev", iface], timeout=8)
    for line in r.stdout.splitlines():
        parts = line.split()
        if "via" in parts:
            return parts[parts.index("via") + 1]
    # Some DHCP setups put the default in a per-link table; fall back to any
    # 'via' on the link.
    r2 = shell.run(["ip", "-o", "route", "show", "dev", iface], timeout=8)
    for line in r2.stdout.splitlines():
        parts = line.split()
        if parts[:1] == ["default"] and "via" in parts:
            return parts[parts.index("via") + 1]
    return None


def _src_ip(iface: str) -> str | None:
    r = shell.run(["ip", "-o", "-4", "addr", "show", "dev", iface], timeout=8)
    for line in r.stdout.splitlines():
        parts = line.split()
        if "inet" in parts:
            return parts[parts.index("inet") + 1].split("/")[0]
    return None


def _effective_gateway(g: dict[str, Any]) -> str | None:
    if g["gateway"] and g["gateway"] != "auto":
        return g["gateway"]
    return _resolve_gateway(g["iface"])


# ---------------------------------------------------------- health -----------

def _ping(iface: str, target: str) -> tuple[bool, float | None]:
    """Ping a target *through* a specific interface. Returns (alive, rtt_ms)."""
    r = shell.run(
        ["ping", "-c", "2", "-w", "3", "-i", "0.3", "-I", iface, target],
        timeout=8)
    if not r.ok:
        return (False, None)
    m = re.search(r"=\s*[\d.]+/([\d.]+)/", r.stdout)
    return (True, float(m.group(1)) if m else None)


def _eval_gateway(model: dict[str, Any], g: dict[str, Any]) -> bool:
    """Run one health probe and update the hysteresis state. Returns whether a
    transition (up<->down) occurred."""
    st = _health.setdefault(g["id"], {
        "up": True, "fails": 0, "oks": 0, "latency": None, "last_change": time.time(),
    })
    alive, rtt = _ping(g["iface"], g["monitor_ip"])
    st["latency"] = rtt
    changed = False
    if alive:
        st["oks"] += 1
        st["fails"] = 0
        if not st["up"] and st["oks"] >= model["up_after"]:
            st["up"] = True
            st["last_change"] = time.time()
            changed = True
    else:
        st["fails"] += 1
        st["oks"] = 0
        if st["up"] and st["fails"] >= model["down_after"]:
            st["up"] = False
            st["last_change"] = time.time()
            changed = True
    return changed


# ---------------------------------------------------------- routing ----------

def _active_gateways(model: dict[str, Any]) -> list[dict[str, Any]]:
    """Gateways that should currently carry traffic, honouring mode + health.
    Falls back to the best-configured gateway if everything is down so the box
    is never left without a default route."""
    enabled = [g for g in model["gateways"] if g.get("enabled")]
    if not enabled:
        return []
    up = [g for g in enabled if _health.get(g["id"], {}).get("up", True)]
    pool = up or enabled  # safety: never strand the appliance
    best_tier = min(g["tier"] for g in pool)
    tier_pool = [g for g in pool if g["tier"] == best_tier]
    if model["mode"] == "loadbalance":
        return tier_pool
    # failover: single best link (highest weight breaks ties)
    return [max(tier_pool, key=lambda g: g["weight"])]


def _build_default_cmd(actives: list[dict[str, Any]]) -> list[str] | None:
    nexthops: list[tuple[str, str, int]] = []
    for g in actives:
        gw = _effective_gateway(g)
        if gw:
            nexthops.append((gw, g["iface"], max(1, g["weight"])))
    if not nexthops:
        return None
    if len(nexthops) == 1:
        gw, iff, _ = nexthops[0]
        return ["ip", "route", "replace", "default", "via", gw, "dev", iff]
    cmd = ["ip", "route", "replace", "default"]
    for gw, iff, w in nexthops:
        cmd += ["nexthop", "via", gw, "dev", iff, "weight", str(w)]
    return cmd


def _clear_source_routing(model: dict[str, Any] | None = None) -> None:
    """Flush the entire owned band (priorities 11000.., tables 200..) regardless
    of the current gateway count, so reconfigure/disable never leaks stale rules."""
    for i in range(_MAX_SLOTS):
        prio = _RULE_PRIO_BASE + i
        tid = _TABLE_ID_BASE + i
        # Remove any rule we own at this priority (loop until none left).
        for _ in range(4):
            r = shell.run(["ip", "rule", "del", "priority", str(prio)], timeout=8)
            if not r.ok:
                break
        shell.run(["ip", "route", "flush", "table", str(tid)], timeout=8)


def _apply_source_routing(model: dict[str, Any]) -> None:
    """Per-link tables so the appliance's own replies are symmetric."""
    _clear_source_routing()
    for i, g in enumerate(model["gateways"]):
        if not g.get("enabled"):
            continue
        gw = _effective_gateway(g)
        src = _src_ip(g["iface"])
        if not gw or not src:
            continue
        tid = _TABLE_ID_BASE + i
        prio = _RULE_PRIO_BASE + i
        shell.run(["ip", "route", "replace", "default", "via", gw,
                   "dev", g["iface"], "table", str(tid)], timeout=8)
        shell.run(["ip", "rule", "add", "from", src, "table", str(tid),
                   "priority", str(prio)], timeout=8)


def _apply_nat(model: dict[str, Any]) -> None:
    """Dedicated NAT table masquerading out every configured WAN member, so
    traffic egressing any active link is translated. Isolated from fwmanage."""
    ifaces = sorted({g["iface"] for g in model["gateways"] if g.get("enabled")})
    _delete_nat()
    if not ifaces:
        return
    oifset = "{ " + ", ".join(f'"{_v_iface(i)}"' for i in ifaces) + " }"
    rules = (
        f"table ip {MWAN_NFT_TABLE} {{\n"
        f"    chain postrouting {{\n"
        f"        type nat hook postrouting priority 90; policy accept;\n"
        f"        oifname {oifset} masquerade\n"
        f"    }}\n"
        f"}}\n"
    )
    shell.run(["nft", "-f", "-"], input_text=rules, timeout=10)


def _delete_nat() -> None:
    shell.run(["nft", "delete", "table", "ip", MWAN_NFT_TABLE], timeout=8)


def apply_routing(model: dict[str, Any] | None = None) -> dict[str, Any]:
    """Install the default route, source-routing tables and NAT for the current
    health state. No-op (and tears down) when disabled."""
    with _lock:
        if model is None:
            model = load_model()
        if not model.get("enabled"):
            return {"applied": False, "reason": "disabled"}
        actives = _active_gateways(model)
        cmd = _build_default_cmd(actives)
        applied_gw = []
        if cmd:
            r = shell.run(cmd, timeout=10)
            if r.ok:
                applied_gw = [g["name"] for g in actives]
            shell.run(["ip", "route", "flush", "cache"], timeout=8)
        _apply_source_routing(model)
        _apply_nat(model)
        return {"applied": True, "mode": model["mode"], "active": applied_gw}


# ------------------------------------------------------- monitor loop --------

def _monitor_loop() -> None:
    while not _monitor_stop.is_set():
        try:
            model = load_model()
            if model.get("enabled") and model["gateways"]:
                changed = False
                for g in model["gateways"]:
                    if g.get("enabled"):
                        changed |= _eval_gateway(model, g)
                # Re-assert routing every tick (self-correct after netplan apply);
                # apply immediately on any health transition. Bail if a disable
                # arrived mid-tick so we never re-install torn-down routing.
                if not _monitor_stop.is_set():
                    apply_routing(model)
                _ = changed
            interval = max(3, int(load_model().get("interval", 10)))
        except Exception:
            interval = 10
        _monitor_stop.wait(interval)


def start_monitor() -> None:
    global _monitor_thread
    with _lock:
        if _monitor_thread and _monitor_thread.is_alive():
            return
        model = load_model()
        if not model.get("enabled"):
            return
        _monitor_stop.clear()
        _monitor_thread = threading.Thread(target=_monitor_loop, daemon=True,
                                           name="mwan-monitor")
        _monitor_thread.start()


def stop_monitor() -> None:
    _monitor_stop.set()
    t = _monitor_thread
    if t and t.is_alive() and t is not threading.current_thread():
        t.join(timeout=5)


# ---------------------------------------------------------- teardown ---------

def _restore_single_wan(model: dict[str, Any], fallback: dict[str, Any] | None = None) -> None:
    """On disable, remove our source rules/NAT and hand the default route back
    to the primary (lowest-tier) configured gateway so the box keeps working.
    Uses `fallback` (the previously-applied config) if the new model has no
    enabled gateway to restore from."""
    _clear_source_routing()
    _delete_nat()
    enabled = [g for g in model["gateways"] if g.get("enabled")]
    if not enabled and fallback:
        enabled = [g for g in fallback.get("gateways", []) if g.get("enabled")]
    if enabled:
        primary = min(enabled, key=lambda g: (g["tier"], -g["weight"]))
        gw = _effective_gateway(primary)
        if gw:
            shell.run(["ip", "route", "replace", "default", "via", gw,
                       "dev", primary["iface"]], timeout=10)
    shell.run(["ip", "route", "flush", "cache"], timeout=8)


# ------------------------------------------------------------ public API -----

def get_status() -> dict[str, Any]:
    model = load_model()
    gws = []
    for g in model["gateways"]:
        st = _health.get(g["id"], {})
        gws.append({
            **g,
            "effective_gateway": _effective_gateway(g),
            "src_ip": _src_ip(g["iface"]),
            "up": st.get("up", None),
            "latency_ms": st.get("latency"),
            "last_change": st.get("last_change"),
        })
    actives = _active_gateways(model) if model.get("enabled") else []
    return {
        "enabled": model["enabled"],
        "mode": model["mode"],
        "interval": model["interval"],
        "down_after": model["down_after"],
        "up_after": model["up_after"],
        "monitor_running": bool(_monitor_thread and _monitor_thread.is_alive()),
        "active_gateways": [g["name"] for g in actives],
        "gateways": gws,
    }


def _validate(model: dict[str, Any]) -> None:
    if model["mode"] not in ("failover", "loadbalance"):
        raise ValueError("modo deve ser 'failover' ou 'loadbalance'")
    live = _live_ifaces()
    seen = set()
    for g in model["gateways"]:
        _v_iface(g["iface"])
        if live and g["iface"] not in live:
            raise ValueError(f"interface '{g['iface']}' não existe neste appliance")
        if g["iface"] in seen:
            raise ValueError(f"interface '{g['iface']}' duplicada entre gateways")
        seen.add(g["iface"])
        if g["gateway"] and g["gateway"] != "auto":
            try:
                ipaddress.ip_address(g["gateway"])
            except ValueError:
                raise ValueError(f"gateway inválido: {g['gateway']}")
        try:
            ipaddress.ip_address(g["monitor_ip"])
        except ValueError:
            raise ValueError(f"IP de monitoramento inválido: {g['monitor_ip']}")
    if model["enabled"] and len([g for g in model["gateways"] if g["enabled"]]) < 1:
        raise ValueError("habilite ao menos um gateway")


def _live_ifaces() -> set[str]:
    try:
        from . import system
        return {i["interface"] for i in system.interfaces() if i.get("interface")}
    except Exception:
        return set()


def set_config(data: dict[str, Any]) -> dict[str, Any]:
    """Replace the whole configuration, (re)applying routing as needed."""
    model = _default_model()
    model.update({
        "enabled": bool(data.get("enabled", False)),
        "mode": data.get("mode", "failover"),
        "interval": int(data.get("interval") or 10),
        "down_after": int(data.get("down_after") or 3),
        "up_after": int(data.get("up_after") or 2),
    })
    model["gateways"] = [_norm_gateway(g) for g in data.get("gateways", [])
                         if g.get("iface")]
    _validate(model)
    with _lock:
        was = load_model()
        _save_model(model)
    if model["enabled"]:
        with _lock:
            # Seed health optimistically so a freshly enabled link routes at once.
            for g in model["gateways"]:
                _health.setdefault(g["id"], {
                    "up": True, "fails": 0, "oks": 0, "latency": None,
                    "last_change": time.time()})
        apply_routing(model)
        start_monitor()
    elif was.get("enabled"):
        # Stop+join the monitor OUTSIDE the lock first (the monitor itself takes
        # _lock in apply_routing — joining while holding it would deadlock), then
        # tear down so a stale tick can never re-assert routing afterwards.
        stop_monitor()
        with _lock:
            _restore_single_wan(model, was)
    return get_status()
