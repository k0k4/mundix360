"""Threat Intelligence feeds — proactive IP/CIDR blocking via nftables.

Downloads public, no-auth IOC blocklists (malware C2, botnets, hijacked
ranges, attackers) on a schedule and enforces them in a dedicated, reboot-safe
nftables table ``ip mundix_ti``.

Design (mirrors fwmanage.py / contentcat.py):
  - Each feed is stream-downloaded with a byte cap and cached raw to disk.
  - The merged, de-overlapped set of GLOBALLY-ROUTABLE networks is rendered to
    ``/etc/nftables.d/mundix-threatintel.nft`` and included from
    ``/etc/nftables.conf`` so the state survives reboot.
  - Apply is transactional: render candidate -> ``nft -c -f`` (validate) ->
    ``nft -f`` (apply live, atomic) -> commit managed file -> ensure include ->
    validate the full ``/etc/nftables.conf`` -> persist JSON.

Anti-lockout layers:
  1. Only globally-routable addresses ever enter the block set (private,
     loopback, link-local, multicast, reserved and unspecified ranges are
     filtered out at parse time), so internal/LAN traffic can never be dropped.
  2. ``ct state established,related accept`` is first in every chain, so an
     in-progress admin session survives even if its source IP appears in a feed
     (only NEW connections from bad IPs are dropped).
  3. An operator allowlist (``ti_allow``) is matched before the drop. NOTE:
     ``ti_allow`` only overrides THESE feeds — it does not override the manual
     dashboard blocklist (table ip mundix_blocklist, priority -200).
  4. ``nft -c`` validation before any live apply.
"""

from __future__ import annotations

import ipaddress
import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Iterable

import httpx

from ..config import settings
from . import fwmanage, shell

# --------------------------------------------------------------- constants ---

MANAGED_FILE = "/etc/nftables.d/mundix-threatintel.nft"
NFTABLES_CONF = "/etc/nftables.conf"
INCLUDE_LINE = f'include "{MANAGED_FILE}"'
MODEL_PATH = os.path.join(settings.base_dir, "dashboard/backend/data/threatintel.json")
CACHE_DIR = os.path.join(settings.base_dir, "dashboard/backend/data/ti_cache")

HOOK_PRIORITY = -150  # after mundix_blocklist(-200), before inet filter(0)
DOWNLOAD_TIMEOUT = 60
MAX_BYTES = 50 * 1024 * 1024  # 50 MB cap per feed
HARD_CAP = 300_000            # max rendered elements (after collapse)
APPLY_TIMEOUT = 30            # nft -f of a large set can take a moment

_lock = threading.RLock()      # serialise nft apply
_update_lock = threading.Lock()  # serialise feed downloads/updates
_state: dict[str, Any] = {"running": False, "current": None}

# ------------------------------------------------------------- feed catalog ---
# format:
#   "ipline" — one IP or CIDR per line, '#' / ';' comments
#   "cidr"   — one CIDR (or IP) per line, '#' / ';' comments
#   "spamhaus" — "<cidr> ; <ref>"   (';' starts the comment / header lines)
#   "dshield"  — TSV: <start>\t<end>\t<maskbits>\t...

FEEDS: list[dict[str, Any]] = [
    {"id": "spamhaus-drop", "name": "Spamhaus DROP",
     "url": "https://www.spamhaus.org/drop/drop.txt", "format": "spamhaus",
     "category": "hijacked", "default": True,
     "description": "Redes sequestradas/alugadas por cibercriminosos (CIDR)."},
    {"id": "feodo", "name": "Abuse.ch Feodo Tracker",
     "url": "https://feodotracker.abuse.ch/downloads/ipblocklist.txt",
     "format": "ipline", "category": "c2", "default": True,
     "description": "Servidores de comando-e-controle (Dridex, Emotet, etc.)."},
    {"id": "et-compromised", "name": "Emerging Threats — Compromised IPs",
     "url": "https://rules.emergingthreats.net/blockrules/compromised-ips.txt",
     "format": "ipline", "category": "compromised", "default": True,
     "description": "Hosts comprometidos conhecidos (atualizado de hora em hora)."},
    {"id": "et-block", "name": "Emerging Threats — Block IPs",
     "url": "https://rules.emergingthreats.net/fwrules/emerging-Block-IPs.txt",
     "format": "cidr", "category": "attackers", "default": True,
     "description": "Spamhaus DROP + DShield consolidados pela ET (CIDR)."},
    {"id": "dshield", "name": "DShield Top Attackers",
     "url": "https://feeds.dshield.org/block.txt", "format": "dshield",
     "category": "attackers", "default": True,
     "description": "As 20 redes /24 com mais ataques (SANS ISC)."},
    {"id": "blocklist-de", "name": "Blocklist.de — Todos",
     "url": "https://lists.blocklist.de/lists/all.txt", "format": "ipline",
     "category": "attackers", "default": False,
     "description": "Atacantes reportados nos últimos 48h (lista grande)."},
]

FEED_BY_ID = {f["id"]: f for f in FEEDS}

# ----------------------------------------------------------------- parsing ---


def _normalize(token: str) -> ipaddress.IPv4Network | None:
    """Return a validated, globally-routable IPv4 network, else None."""
    token = token.strip()
    if not token:
        return None
    try:
        net = ipaddress.ip_network(token, strict=False)
    except ValueError:
        return None
    if not isinstance(net, ipaddress.IPv4Network):
        return None  # IPv4 set only
    # Never block non-global ranges (anti-lockout / never touch internal nets).
    if (net.is_private or net.is_loopback or net.is_link_local
            or net.is_multicast or net.is_reserved or net.is_unspecified):
        return None
    return net


def _parse(text: str, fmt: str) -> set[ipaddress.IPv4Network]:
    out: set[ipaddress.IPv4Network] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if fmt == "spamhaus":
            if line.startswith(";"):
                continue
            tok = line.split(";", 1)[0].strip()
        elif fmt == "dshield":
            if line.startswith(("Start", "#")):
                continue
            cols = line.split("\t")
            if len(cols) < 3:
                cols = line.split()
            if len(cols) < 3:
                continue
            tok = f"{cols[0]}/{cols[2]}"
        else:  # ipline / cidr
            tok = line.split("#", 1)[0].split(";", 1)[0].strip()
            tok = tok.split()[0] if tok.split() else ""
        net = _normalize(tok)
        if net is not None:
            out.add(net)
    return out


def _collapse(nets: Iterable[ipaddress.IPv4Network]) -> list[ipaddress.IPv4Network]:
    return list(ipaddress.collapse_addresses(nets))


# ------------------------------------------------------------------- model ---


def _default_model() -> dict[str, Any]:
    return {
        "feeds": {f["id"]: {"enabled": f["default"], "last_updated": None,
                            "count": 0, "last_error": None} for f in FEEDS},
        "allowlist": [],
        "block_egress": True,
        "schedule": {"enabled": True, "interval_hours": 6},
        "blocked_count": 0,
        "last_apply": None,
    }


def load_model() -> dict[str, Any]:
    try:
        with open(MODEL_PATH) as f:
            model = json.load(f)
    except (OSError, json.JSONDecodeError):
        return _default_model()
    base = _default_model()
    base.update({k: v for k, v in model.items() if k in base})
    # ensure every known feed has a state entry (catalog may have grown)
    feeds = base.get("feeds", {})
    for f in FEEDS:
        feeds.setdefault(f["id"], {"enabled": f["default"], "last_updated": None,
                                   "count": 0, "last_error": None})
    base["feeds"] = {k: v for k, v in feeds.items() if k in FEED_BY_ID}
    return base


def _save_model(model: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    _atomic_write(MODEL_PATH, json.dumps(model, indent=2))


def _atomic_write(path: str, content: str, mode: int = 0o644) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(content)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


# ------------------------------------------------------------------ render ---


def _render_set(name: str, nets: list[ipaddress.IPv4Network]) -> list[str]:
    L = [f"    set {name} {{",
         "        type ipv4_addr",
         "        flags interval",
         "        auto-merge"]
    if nets:
        elems = ", ".join(str(n) for n in nets)
        L.append(f"        elements = {{ {elems} }}")
    L.append("    }")
    return L


def render(blocked: list[ipaddress.IPv4Network],
           allow: list[ipaddress.IPv4Network], *, block_egress: bool) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    L: list[str] = []
    a = L.append
    a("#!/usr/sbin/nft -f")
    a("# AUTO-GERADO pelo Mundix360 (Threat Intelligence).")
    a(f"# Atualizado: {ts} — {len(blocked)} redes maliciosas. Não edite à mão.")
    a("")
    # boot-safe / re-apply-safe replacement
    a("table ip mundix_ti")
    a("delete table ip mundix_ti")
    a("table ip mundix_ti {")
    L.extend(_render_set("ti_allow", allow))
    L.extend(_render_set("ti_blocked", blocked))
    a("    chain input {")
    a(f"        type filter hook input priority {HOOK_PRIORITY}; policy accept;")
    a("        ct state established,related accept")
    a("        ip saddr @ti_allow accept")
    a("        ip saddr @ti_blocked drop")
    a("    }")
    a("    chain forward {")
    a(f"        type filter hook forward priority {HOOK_PRIORITY}; policy accept;")
    a("        ct state established,related accept")
    a("        ip saddr @ti_allow accept")
    a("        ip saddr @ti_blocked drop")
    if block_egress:
        a("        ip daddr @ti_blocked drop")
    a("    }")
    a("}")
    a("")
    return "\n".join(L)


# ------------------------------------------------------------------- apply ---


def _ensure_include() -> None:
    # /etc/nftables.conf is also edited by fwmanage; share its lock to avoid a
    # lost-update race on the read-modify-write.
    with fwmanage._lock:  # noqa: SLF001 — intentional shared serialization
        try:
            with open(NFTABLES_CONF) as f:
                content = f.read()
        except OSError:
            return
        if INCLUDE_LINE in content:
            return
        if not content.endswith("\n"):
            content += "\n"
        content += f"\n# Mundix360 Threat Intelligence\n{INCLUDE_LINE}\n"
        _atomic_write(NFTABLES_CONF, content, mode=0o755)


def _build_sets(model: dict[str, Any]) -> tuple[list, list]:
    """Merge cached feeds (enabled only) + allowlist into collapsed net lists."""
    blocked: set[ipaddress.IPv4Network] = set()
    for fid, st in model.get("feeds", {}).items():
        if not st.get("enabled") or fid not in FEED_BY_ID:
            continue
        path = os.path.join(CACHE_DIR, f"{fid}.txt")
        try:
            with open(path) as f:
                for ln in f:
                    net = _normalize(ln)
                    if net is not None:
                        blocked.add(net)
        except OSError:
            continue
    allow: set[ipaddress.IPv4Network] = set()
    for tok in model.get("allowlist", []):
        net = _normalize(tok)
        if net is not None:
            allow.add(net)
    blocked_l = _collapse(blocked)
    if len(blocked_l) > HARD_CAP:
        blocked_l = sorted(blocked_l, key=lambda n: (int(n.network_address), n.prefixlen))[:HARD_CAP]
    return blocked_l, _collapse(allow)


def apply_model(model: dict[str, Any], *, persist: bool = True) -> dict[str, Any]:
    """Render from caches + persisted state, validate, apply live, commit."""
    warnings: list[str] = []
    with _lock:
        blocked, allow = _build_sets(model)
        content = render(blocked, allow, block_egress=model.get("block_egress", True))
        os.makedirs(os.path.dirname(MANAGED_FILE), exist_ok=True)
        candidate = MANAGED_FILE + ".candidate"
        _atomic_write(candidate, content)
        try:
            chk = shell.run(["nft", "-c", "-f", candidate], timeout=APPLY_TIMEOUT)
            if not chk.ok:
                raise ValueError(f"validação nft falhou: {chk.stderr.strip()}")
            ap = shell.run(["nft", "-f", candidate], timeout=APPLY_TIMEOUT)
            if not ap.ok:
                raise RuntimeError(f"aplicação nft falhou: {ap.stderr.strip()}")
            os.replace(candidate, MANAGED_FILE)
            _ensure_include()
            # confirm the whole config (with the include) reloads cleanly
            full = shell.run(["nft", "-c", "-f", NFTABLES_CONF], timeout=APPLY_TIMEOUT)
            if not full.ok:
                warnings.append(
                    "atenção: /etc/nftables.conf não validou após include — "
                    f"verifique antes do reboot: {full.stderr.strip()}")
            model["blocked_count"] = len(blocked)
            model["last_apply"] = datetime.now(timezone.utc).isoformat()
            if persist:
                _save_model(model)
        finally:
            if os.path.exists(candidate):
                try:
                    os.remove(candidate)
                except OSError:
                    pass
    return {"ok": True, "blocked_count": len(blocked), "allow_count": len(allow),
            "warnings": warnings}


# ----------------------------------------------------------------- updates ---


def _download(feed: dict[str, Any]) -> set[ipaddress.IPv4Network]:
    total = 0
    chunks: list[str] = []
    with httpx.Client(follow_redirects=True, timeout=DOWNLOAD_TIMEOUT,
                      headers={"User-Agent": "Mundix360-ThreatIntel/1.0"},
                      max_redirects=5) as client:
        with client.stream("GET", feed["url"]) as resp:
            resp.raise_for_status()
            for chunk in resp.iter_text():
                total += len(chunk)
                if total > MAX_BYTES:
                    raise ValueError("feed excede o tamanho máximo permitido")
                chunks.append(chunk)
    return _parse("".join(chunks), feed["format"])


def _refresh_feed(model: dict[str, Any], fid: str) -> None:
    """Download one feed and update its cache + state (no apply)."""
    feed = FEED_BY_ID[fid]
    st = model["feeds"].setdefault(
        fid, {"enabled": feed["default"], "last_updated": None, "count": 0, "last_error": None})
    try:
        nets = _download(feed)
        os.makedirs(CACHE_DIR, exist_ok=True)
        _atomic_write(os.path.join(CACHE_DIR, f"{fid}.txt"),
                      "".join(f"{n}\n" for n in sorted(nets, key=lambda x: int(x.network_address))))
        st["count"] = len(nets)
        st["last_updated"] = datetime.now(timezone.utc).isoformat()
        st["last_error"] = None
    except Exception as e:  # noqa: BLE001 — record per-feed failure, keep going
        st["last_error"] = f"{type(e).__name__}: {e}"


def update_feeds(fids: list[str] | None = None) -> dict[str, Any]:
    """Download the given feeds (or all enabled) and re-apply the ruleset."""
    model = load_model()
    if fids is None:
        fids = [fid for fid, st in model["feeds"].items() if st.get("enabled")]
    targets = [f for f in fids if f in FEED_BY_ID]
    for fid in targets:
        _state["current"] = fid
        _refresh_feed(model, fid)
    _state["current"] = None
    res = apply_model(model)
    res["updated"] = targets
    return res


def manual_update(fids: list[str] | None = None) -> dict[str, Any]:
    if not _update_lock.acquire(timeout=1):
        raise RuntimeError("uma atualização já está em andamento")
    try:
        _state["running"] = True
        return update_feeds(fids)
    finally:
        _state["running"] = False
        _update_lock.release()


# ---------------------------------------------------------------- mutations ---


def set_feed_enabled(fid: str, enabled: bool) -> dict[str, Any]:
    if fid not in FEED_BY_ID:
        raise KeyError(fid)
    model = load_model()
    st = model["feeds"].setdefault(
        fid, {"enabled": False, "last_updated": None, "count": 0, "last_error": None})
    st["enabled"] = bool(enabled)
    # if enabling and no cache yet, fetch it now
    cache = os.path.join(CACHE_DIR, f"{fid}.txt")
    if enabled and not os.path.exists(cache):
        _refresh_feed(model, fid)
    return apply_model(model)


def set_allowlist(entries: list[str]) -> dict[str, Any]:
    cleaned: list[str] = []
    for e in entries:
        net = _normalize(e)
        if net is None:
            raise ValueError(f"entrada inválida ou não-roteável: {e!r}")
        cleaned.append(str(net))
    model = load_model()
    model["allowlist"] = sorted(set(cleaned))
    return apply_model(model)


def set_egress(block_egress: bool) -> dict[str, Any]:
    model = load_model()
    model["block_egress"] = bool(block_egress)
    return apply_model(model)


def set_schedule(enabled: bool, interval_hours: int) -> dict[str, Any]:
    model = load_model()
    model["schedule"] = {"enabled": bool(enabled),
                         "interval_hours": max(1, min(168, int(interval_hours)))}
    _save_model(model)
    return model["schedule"]


# ----------------------------------------------------------------- overview ---


def overview() -> dict[str, Any]:
    model = load_model()
    feeds = []
    for f in FEEDS:
        st = model["feeds"].get(f["id"], {})
        feeds.append({**{k: f[k] for k in ("id", "name", "category", "description")},
                      "enabled": st.get("enabled", False),
                      "count": st.get("count", 0),
                      "last_updated": st.get("last_updated"),
                      "last_error": st.get("last_error")})
    return {
        "feeds": feeds,
        "allowlist": model.get("allowlist", []),
        "block_egress": model.get("block_egress", True),
        "schedule": model.get("schedule", {"enabled": True, "interval_hours": 6}),
        "blocked_count": model.get("blocked_count", 0),
        "last_apply": model.get("last_apply"),
        "running": _state["running"],
        "current": _state["current"],
    }


# ---------------------------------------------------------------- scheduler ---


def run_due_updates() -> None:
    model = load_model()
    interval = model.get("schedule", {}).get("interval_hours", 6) * 3600
    now = datetime.now(timezone.utc)
    due: list[str] = []
    for fid, st in model["feeds"].items():
        if not st.get("enabled") or fid not in FEED_BY_ID:
            continue
        lu = st.get("last_updated")
        if lu is None:
            due.append(fid)
            continue
        try:
            age = (now - datetime.fromisoformat(lu)).total_seconds()
        except ValueError:
            age = interval + 1
        if age >= interval:
            due.append(fid)
    if due:
        update_feeds(due)


def _scheduler_loop() -> None:
    time.sleep(150)  # let startup finish before any network I/O
    while True:
        try:
            model = load_model()
            if model.get("schedule", {}).get("enabled", True):
                if _update_lock.acquire(blocking=False):
                    try:
                        _state["running"] = True
                        run_due_updates()
                    finally:
                        _state["running"] = False
                        _update_lock.release()
        except Exception:  # noqa: BLE001 — scheduler must never die
            _state["running"] = False
        time.sleep(1800)  # re-check every 30 min


def start_scheduler() -> None:
    t = threading.Thread(target=_scheduler_loop, name="threatintel-scheduler", daemon=True)
    t.start()
