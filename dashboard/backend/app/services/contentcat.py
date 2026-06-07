"""Category-based content filtering via downloadable DNS blocklists.

Downloads well-known, frequently-updated blocklists (by category: adult,
gambling, malware, phishing, etc.), parses them into domains and renders one
dnsmasq sinkhole file per category (``address=/domain/0.0.0.0``, which
wildcard-blocks the domain and every subdomain).

Safety model (see design review):
  * Downloads happen OUTSIDE the dnsmasq config lock; only the
    write -> validate -> restart critical section holds ``config_lock``.
  * A whole batch of file changes is applied transactionally: snapshot every
    touched file, write, ``dnsmasq --test``, restart (long timeout) and verify
    ``is-active``; on any failure every touched file is restored to its exact
    previous state (content or absence) and dnsmasq is restarted again.
  * Generated lines are NEVER raw input — only ``address=/<regex-validated
    domain>/0.0.0.0`` — so a malicious list line cannot inject dnsmasq
    directives. Category/source IDs are whitelisted before being used in paths.
  * Allowlist (exceptions) are emitted as ``server=/domain/#`` (most-specific
    match wins in dnsmasq) so they override category/manual blocks.
  * Content hashing skips restarts when nothing actually changed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime, timezone

import httpx

from ..config import settings
from . import network, shell

# --------------------------------------------------------------- constants ---

ETC_DIR = settings.dnsmasq_etc_dir
CAT_PREFIX = "mundix-cat-"
ALLOW_FILE = os.path.join(ETC_DIR, "mundix-content-allow.conf")
MODEL_PATH = os.path.join(settings.base_dir, "dashboard/backend/data/content_filter.json")
CACHE_DIR = os.path.join(settings.base_dir, "dashboard/backend/data/content_cache")

RESTART_TIMEOUT = 150  # large category files take longer to load
DOWNLOAD_TIMEOUT = 60
MAX_BYTES = 80 * 1024 * 1024  # 80 MB decompressed cap per source
WARN_THRESHOLD = 100_000  # warn (UI) when a category exceeds this many domains
HARD_CAP = 700_000  # protect the appliance from pathological lists

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9_-]{1,63}\.)+[a-z]{2,63}$")
_HOSTS_RE = re.compile(r"^\s*(?:0\.0\.0\.0|127\.0\.0\.1|::1?)\s+(\S+)")
_ADBLOCK_RE = re.compile(r"^\|\|([^/^*]+)\^?$")

config_lock = network.config_lock  # shared, process-wide
_update_lock = threading.Lock()    # serialise update operations
_state = {"running": False, "current": None}

# ------------------------------------------------------------- source catalog -
# Curated, frequently-updated, free lists. Per-category hosts files from The
# Block List Project map cleanly to the "by category" requirement.

_BLP = "https://raw.githubusercontent.com/blocklistproject/Lists/master/{}.txt"
_HAGEZI = "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/domains/{}.txt"

CATALOG: list[dict] = [
    # id, category, name, url, format, description
    {"id": "blp-porn", "category": "adult", "name": "BlockList Project · Pornografia",
     "url": _BLP.format("porn"), "format": "hosts",
     "description": "~500 mil domínios adultos (grande)"},
    {"id": "blp-gambling", "category": "gambling", "name": "BlockList Project · Apostas",
     "url": _BLP.format("gambling"), "format": "hosts", "description": "Casas de aposta/cassino"},
    {"id": "blp-malware", "category": "malware", "name": "BlockList Project · Malware",
     "url": _BLP.format("malware"), "format": "hosts", "description": "Distribuição de malware"},
    {"id": "blp-phishing", "category": "phishing", "name": "BlockList Project · Phishing",
     "url": _BLP.format("phishing"), "format": "hosts", "description": "Roubo de credenciais"},
    {"id": "blp-ransomware", "category": "malware", "name": "BlockList Project · Ransomware",
     "url": _BLP.format("ransomware"), "format": "hosts", "description": "C2 de ransomware"},
    {"id": "blp-scam", "category": "scam", "name": "BlockList Project · Golpes",
     "url": _BLP.format("scam"), "format": "hosts", "description": "Sites de golpe"},
    {"id": "blp-fraud", "category": "scam", "name": "BlockList Project · Fraude",
     "url": _BLP.format("fraud"), "format": "hosts", "description": "Fraudes online"},
    {"id": "blp-abuse", "category": "hacking", "name": "BlockList Project · Abuso/Hacking",
     "url": _BLP.format("abuse"), "format": "hosts", "description": "Infra de ataque/abuso"},
    {"id": "blp-drugs", "category": "drugs", "name": "BlockList Project · Drogas",
     "url": _BLP.format("drugs"), "format": "hosts", "description": "Venda de drogas"},
    {"id": "blp-crypto", "category": "crypto", "name": "BlockList Project · Cripto-mineração",
     "url": _BLP.format("crypto"), "format": "hosts", "description": "Mineração no navegador"},
    {"id": "blp-ads", "category": "ads", "name": "BlockList Project · Anúncios",
     "url": _BLP.format("ads"), "format": "hosts", "description": "Redes de publicidade"},
    {"id": "blp-tracking", "category": "tracking", "name": "BlockList Project · Rastreadores",
     "url": _BLP.format("tracking"), "format": "hosts", "description": "Telemetria/rastreamento"},
    {"id": "blp-piracy", "category": "piracy", "name": "BlockList Project · Pirataria",
     "url": _BLP.format("piracy"), "format": "hosts", "description": "Conteúdo pirata"},
    {"id": "blp-redirect", "category": "malware", "name": "BlockList Project · Redirecionadores",
     "url": _BLP.format("redirect"), "format": "hosts", "description": "Redirecionadores maliciosos"},
]

# User-facing categories (Portuguese label + icon hint).
CATEGORIES: dict[str, dict] = {
    "adult": {"label": "Pornografia / Adulto", "color": "#f43f5e"},
    "gambling": {"label": "Apostas / Cassino", "color": "#f59e0b"},
    "malware": {"label": "Malware / Ransomware", "color": "#ef4444"},
    "phishing": {"label": "Phishing", "color": "#fb7185"},
    "scam": {"label": "Golpes / Fraude", "color": "#fbbf24"},
    "hacking": {"label": "Hacking / Abuso", "color": "#a855f7"},
    "drugs": {"label": "Drogas", "color": "#84cc16"},
    "crypto": {"label": "Cripto-mineração", "color": "#22d3ee"},
    "ads": {"label": "Anúncios", "color": "#38bdf8"},
    "tracking": {"label": "Rastreadores", "color": "#818cf8"},
    "piracy": {"label": "Pirataria", "color": "#fb923c"},
}


# ------------------------------------------------------------------- model ----


def _default_model() -> dict:
    return {
        "version": 1,
        "categories": {cid: {"enabled": False} for cid in CATEGORIES},
        "custom_sources": [],
        "disabled_sources": [],   # catalog source ids the user turned off
        "allowlist": [],
        "schedule": {"enabled": True, "interval_hours": 24, "last_run": None},
        "status": {},  # per-category: {domain_count, last_success, last_attempt, error, sources}
    }


def load_model() -> dict:
    if os.path.isfile(MODEL_PATH):
        try:
            with open(MODEL_PATH) as f:
                data = json.load(f)
            d = _default_model()
            d.update(data)
            for cid in CATEGORIES:
                d["categories"].setdefault(cid, {"enabled": False})
            d.setdefault("status", {})
            return d
        except (json.JSONDecodeError, OSError):
            pass
    return _default_model()


def _save_model(model: dict) -> None:
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    network._atomic_write(MODEL_PATH, json.dumps(model, indent=2, ensure_ascii=False))


# -------------------------------------------------------------- validation ----


def _valid_id(v: str) -> bool:
    return bool(_ID_RE.match(v))


def validate_domain(d: str) -> bool:
    return bool(_DOMAIN_RE.match(d))


def _cat_path(cid: str) -> str:
    if not _valid_id(cid):
        raise ValueError(f"id de categoria inválido: {cid}")
    return os.path.join(ETC_DIR, f"{CAT_PREFIX}{cid}.conf")


def _cache_path(cid: str) -> str:
    if not _valid_id(cid):
        raise ValueError(f"id de categoria inválido: {cid}")
    return os.path.join(CACHE_DIR, f"{cid}.txt")


def _write_cache(cid: str, domains: set[str]) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    network._atomic_write(_cache_path(cid), "\n".join(sorted(domains)) + "\n")


def _read_cache(cid: str) -> set[str]:
    path = _cache_path(cid)
    if not os.path.isfile(path):
        return set()
    with open(path) as f:
        return {ln.strip() for ln in f if ln.strip()}


def _all_sources(model: dict) -> list[dict]:
    return CATALOG + model.get("custom_sources", [])


def _sources_for(cid: str, model: dict) -> list[dict]:
    disabled = set(model.get("disabled_sources", []))
    return [s for s in _all_sources(model)
            if s.get("category") == cid and s["id"] not in disabled]


# --------------------------------------------------------------- download ----


def _parse_line(line: str) -> str | None:
    line = line.strip()
    if not line or line.startswith(("#", "!", ";")):
        return None
    m = _HOSTS_RE.match(line)
    if m:
        cand = m.group(1)
    elif line.startswith("||"):
        am = _ADBLOCK_RE.match(line)
        if not am:
            return None
        cand = am.group(1)
    else:
        cand = line.split()[0]
    cand = cand.strip().lower().rstrip(".")
    if cand in ("localhost", "localhost.localdomain", "broadcasthost", "0.0.0.0"):
        return None
    return cand if _DOMAIN_RE.match(cand) else None


def _download_domains(url: str) -> set[str]:
    """Stream-download a list and return a set of validated domains."""
    domains: set[str] = set()
    total = 0
    with httpx.Client(follow_redirects=True, timeout=DOWNLOAD_TIMEOUT,
                      headers={"User-Agent": "Mundix360-ContentFilter/1.0"},
                      max_redirects=5) as client:
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            buf = ""
            for chunk in resp.iter_text():
                total += len(chunk)
                if total > MAX_BYTES:
                    raise ValueError("lista excede o tamanho máximo permitido")
                buf += chunk
                lines = buf.split("\n")
                buf = lines.pop()
                for ln in lines:
                    d = _parse_line(ln)
                    if d:
                        domains.add(d)
            d = _parse_line(buf)
            if d:
                domains.add(d)
    return domains


def _render_category(cid: str, domains: set[str], allow: set[str]) -> str:
    cat = CATEGORIES.get(cid, {})
    # exact allowlisted domains must be removed: address= takes precedence over
    # server=/x/# for an identically-named domain, so we cannot un-block them
    # via the allow file. (Subdomains under a wildcard-blocked parent are still
    # handled by the server=/x/# entries in the allow file.)
    effective = domains - allow
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    head = (f"# Mundix360 content filter — categoria: {cat.get('label', cid)}\n"
            f"# Atualizado: {ts} — {len(effective)} domínios\n"
            f"# Gerado automaticamente. Não edite à mão.\n")
    body = "".join(f"address=/{d}/0.0.0.0\n" for d in sorted(effective))
    return head + body


def _render_allowlist(allow: list[str]) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    head = (f"# Mundix360 content filter — exceções (allowlist)\n"
            f"# Atualizado: {ts} — {len(allow)} domínios\n"
            f"# server=/dominio/# força resolução normal, sobrepondo bloqueios.\n")
    body = "".join(f"server=/{d}/#\n" for d in sorted(set(allow)))
    return head + body


# -------------------------------------------------- transactional apply -------


def _sha(content: str | None) -> str:
    return hashlib.sha256((content or "").encode()).hexdigest()


def _apply_batch(changes: dict[str, str | None], *, force: bool = False) -> dict:
    """Apply a set of {path: new_content | None(delete)} transactionally.

    Holds config_lock for the critical section only. Skips the restart if no
    file content actually changes (unless ``force`` — used to recover from a
    previous apply whose restart never completed). On any failure restores
    every file we touched to its exact previous state; only restarts during
    rollback if we had already attempted a restart (a failed ``dnsmasq --test``
    leaves the running config untouched, so restarting then would be unsafe).
    """
    with config_lock:
        # snapshot + detect real changes
        snapshot: dict[str, str | None] = {}
        effective: dict[str, str | None] = {}
        for path, new in changes.items():
            prev = None
            if os.path.isfile(path):
                with open(path) as f:
                    prev = f.read()
            snapshot[path] = prev
            if _sha(prev) != _sha(new):
                effective[path] = new
        if not effective and not force:
            return {"ok": True, "changed": False, "restarted": False}

        written: list[str] = []
        restart_attempted = False
        try:
            # write phase (tracked for rollback)
            for path, new in effective.items():
                written.append(path)
                if new is None:
                    if os.path.isfile(path):
                        os.remove(path)
                else:
                    network._atomic_write(path, new)

            test = shell.run(["dnsmasq", "--test"], timeout=25)
            if not test.ok:
                raise RuntimeError((test.stderr or test.stdout).strip()
                                   or "dnsmasq --test falhou")

            restart_attempted = True
            r = shell.run(["systemctl", "restart", "dnsmasq"], timeout=RESTART_TIMEOUT)
            if not r.ok:
                raise RuntimeError(r.stderr.strip() or "restart falhou")

            act = shell.run(["systemctl", "is-active", "dnsmasq"], timeout=10)
            if act.stdout.strip() != "active":
                raise RuntimeError("dnsmasq não ficou ativo após o restart")

            return {"ok": True, "changed": bool(effective), "restarted": True}

        except Exception as e:  # noqa: BLE001 — rollback then surface
            # restore exactly the files we touched
            for path in written:
                prev = snapshot.get(path)
                if prev is None:
                    if os.path.isfile(path):
                        os.remove(path)
                else:
                    network._atomic_write(path, prev)
            # only restart during rollback if we had already attempted a restart;
            # a failed --test means the live config was never reloaded.
            if restart_attempted:
                shell.run(["systemctl", "restart", "dnsmasq"], timeout=RESTART_TIMEOUT)
            raise RuntimeError(f"falha ao aplicar (revertido): {e}")


# ----------------------------------------------------------------- updates ----


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def update_categories(cat_ids: list[str], *, persist: bool = True) -> dict:
    """Download enabled categories (outside lock) then apply one batch."""
    model = load_model()
    allow = set(model.get("allowlist", []))
    changes: dict[str, str | None] = {}
    results: dict[str, dict] = {}

    for cid in cat_ids:
        if cid not in CATEGORIES:
            continue
        _state["current"] = cid
        st = model["status"].setdefault(cid, {})
        st["last_attempt"] = _now()
        if not model["categories"].get(cid, {}).get("enabled"):
            changes[_cat_path(cid)] = None  # ensure removed when disabled
            cp = _cache_path(cid)
            if os.path.isfile(cp):
                os.remove(cp)
            st["domain_count"] = 0
            results[cid] = {"ok": True, "enabled": False, "count": 0}
            continue
        sources = _sources_for(cid, model)
        domains: set[str] = set()
        errors: list[str] = []
        used: list[str] = []
        for s in sources:
            try:
                got = _download_domains(s["url"])
                domains |= got
                used.append(s["id"])
            except Exception as e:  # noqa: BLE001 — isolate per-source failures
                errors.append(f"{s['id']}: {e}")
        if not used:
            st["error"] = "; ".join(errors) or "nenhuma fonte disponível"
            results[cid] = {"ok": False, "error": st["error"]}
            continue
        truncated = False
        if len(domains) > HARD_CAP:
            domains = set(sorted(domains)[:HARD_CAP])
            truncated = True
        _write_cache(cid, domains)  # raw set, for fast allowlist regeneration
        changes[_cat_path(cid)] = _render_category(cid, domains, allow)
        effective_count = len(domains - allow)
        st.update({
            "domain_count": effective_count,
            "last_success": _now(),
            "error": "; ".join(errors) if errors else None,
            "sources": used,
            "truncated": truncated,
            "large": len(domains) > WARN_THRESHOLD,
        })
        results[cid] = {"ok": True, "count": effective_count, "truncated": truncated,
                        "partial_errors": errors}

    _state["current"] = None
    apply_res = {"ok": True, "changed": False}
    if changes:
        force = bool(model.get("pending_restart"))
        try:
            apply_res = _apply_batch(changes, force=force)
            model["pending_restart"] = False
        except Exception:
            # mark that on-disk state may diverge from the running config so the
            # next successful apply forces a restart to reconcile.
            model["pending_restart"] = True
            if persist:
                _save_model(model)
            raise
    if persist:
        _save_model(model)
    return {"applied": apply_res, "categories": results}


def set_category_enabled(cid: str, enabled: bool) -> dict:
    if cid not in CATEGORIES:
        raise ValueError(f"categoria desconhecida: {cid}")
    model = load_model()
    prev = model["categories"].get(cid, {}).get("enabled", False)
    model["categories"][cid] = {"enabled": bool(enabled)}
    _save_model(model)
    try:
        # enabling downloads+writes; disabling removes the file
        return update_categories([cid])
    except Exception:
        # revert the intent flag so the model never claims a state we failed
        # to apply to the running resolver.
        m = load_model()
        m["categories"][cid] = {"enabled": bool(prev)}
        _save_model(m)
        raise


def update_all(force: bool = False) -> dict:
    model = load_model()
    enabled = [cid for cid, c in model["categories"].items() if c.get("enabled")]
    return update_categories(enabled or list(CATEGORIES))


# ----------------------------------------------------------------- allowlist --


def get_allowlist() -> list[str]:
    return load_model().get("allowlist", [])


def set_allowlist(domains: list[str]) -> dict:
    clean = []
    for d in domains:
        d = d.strip().lower().rstrip(".")
        if not validate_domain(d):
            raise ValueError(f"domínio inválido: {d}")
        clean.append(d)
    clean = sorted(set(clean))
    allow = set(clean)
    model = load_model()

    # rebuild every enabled category from its cached raw set (no re-download),
    # subtracting the new allowlist, plus refresh the server=/x/# allow file.
    changes: dict[str, str | None] = {
        ALLOW_FILE: _render_allowlist(clean) if clean else None,
    }
    for cid, c in model["categories"].items():
        if not c.get("enabled"):
            continue
        cached = _read_cache(cid)
        if not cached:
            continue
        changes[_cat_path(cid)] = _render_category(cid, cached, allow)
        model["status"].setdefault(cid, {})["domain_count"] = len(cached - allow)

    model["allowlist"] = clean
    force = bool(model.get("pending_restart"))
    try:
        _apply_batch(changes, force=force)
        model["pending_restart"] = False
    except Exception:
        model["pending_restart"] = True
        _save_model(model)
        raise
    _save_model(model)
    return {"ok": True, "count": len(clean)}


# ------------------------------------------------------------- custom sources -


def add_custom_source(src: dict) -> dict:
    if not _valid_id(src.get("id", "")):
        raise ValueError("id inválido (use a-z, 0-9, _-)")
    if src.get("category") not in CATEGORIES:
        raise ValueError("categoria desconhecida")
    if src.get("format") not in ("hosts", "domains", "adblock"):
        raise ValueError("formato deve ser hosts, domains ou adblock")
    url = src.get("url", "")
    if not url.startswith(("http://", "https://")):
        raise ValueError("URL deve começar com http(s)://")
    model = load_model()
    if any(s["id"] == src["id"] for s in _all_sources(model)):
        raise ValueError(f"fonte '{src['id']}' já existe")
    model["custom_sources"].append({
        "id": src["id"], "category": src["category"], "name": src.get("name", src["id"]),
        "url": url, "format": src["format"], "description": src.get("description", ""),
        "custom": True,
    })
    _save_model(model)
    return {"ok": True}


def delete_custom_source(sid: str) -> dict:
    model = load_model()
    model["custom_sources"] = [s for s in model["custom_sources"] if s["id"] != sid]
    model["disabled_sources"] = [d for d in model.get("disabled_sources", []) if d != sid]
    _save_model(model)
    return {"ok": True}


def toggle_source(sid: str, enabled: bool) -> dict:
    model = load_model()
    dis = set(model.get("disabled_sources", []))
    if enabled:
        dis.discard(sid)
    else:
        dis.add(sid)
    model["disabled_sources"] = sorted(dis)
    _save_model(model)
    return {"ok": True}


# ----------------------------------------------------------------- schedule ---


def get_schedule() -> dict:
    return load_model().get("schedule", {"enabled": True, "interval_hours": 24})


def set_schedule(enabled: bool, interval_hours: int) -> dict:
    interval_hours = max(1, min(int(interval_hours), 24 * 30))
    model = load_model()
    sched = model.get("schedule", {})
    sched.update({"enabled": bool(enabled), "interval_hours": interval_hours})
    model["schedule"] = sched
    _save_model(model)
    return sched


# ------------------------------------------------------------------ overview --


def overview() -> dict:
    model = load_model()
    cats = []
    disabled = set(model.get("disabled_sources", []))
    for cid, meta in CATEGORIES.items():
        st = model["status"].get(cid, {})
        srcs = [s for s in _all_sources(model) if s.get("category") == cid]
        cats.append({
            "id": cid,
            "label": meta["label"],
            "color": meta["color"],
            "enabled": model["categories"].get(cid, {}).get("enabled", False),
            "domain_count": st.get("domain_count", 0),
            "last_success": st.get("last_success"),
            "last_attempt": st.get("last_attempt"),
            "error": st.get("error"),
            "large": st.get("large", False),
            "truncated": st.get("truncated", False),
            "source_count": len(srcs),
            "active_source_count": len([s for s in srcs if s["id"] not in disabled]),
        })
    total = sum(c["domain_count"] for c in cats if c["enabled"])
    return {
        "categories": cats,
        "total_blocked": total,
        "enabled_categories": sum(1 for c in cats if c["enabled"]),
        "allowlist_count": len(model.get("allowlist", [])),
        "schedule": model.get("schedule", {}),
        "running": _state["running"],
        "current": _state["current"],
        "warn_threshold": WARN_THRESHOLD,
    }


def list_catalog() -> list[dict]:
    model = load_model()
    disabled = set(model.get("disabled_sources", []))
    out = []
    for s in _all_sources(model):
        out.append({**s, "enabled": s["id"] not in disabled,
                    "custom": s.get("custom", False)})
    return out


# ----------------------------------------------------------------- scheduler --


def run_due_updates() -> dict | None:
    """Called by the scheduler: update enabled categories that are stale."""
    model = load_model()
    sched = model.get("schedule", {})
    if not sched.get("enabled"):
        return None
    interval = sched.get("interval_hours", 24) * 3600
    now = time.time()
    due: list[str] = []
    for cid, c in model["categories"].items():
        if not c.get("enabled"):
            continue
        st = model["status"].get(cid, {})
        last = st.get("last_success")
        if not last:
            due.append(cid)
            continue
        try:
            last_ts = datetime.fromisoformat(last).timestamp()
        except ValueError:
            last_ts = 0
        if now - last_ts >= interval:
            due.append(cid)
    if not due:
        return None
    res = update_categories(due)
    model = load_model()
    model.setdefault("schedule", {})["last_run"] = _now()
    _save_model(model)
    return res


def _scheduler_loop() -> None:
    # initial delay so startup isn't blocked by network I/O
    time.sleep(120)
    while True:
        try:
            if _update_lock.acquire(blocking=False):
                try:
                    _state["running"] = True
                    run_due_updates()
                finally:
                    _state["running"] = False
                    _update_lock.release()
        except Exception:  # noqa: BLE001 — scheduler must never die
            _state["running"] = False
        time.sleep(900)  # re-check every 15 min


def start_scheduler() -> None:
    t = threading.Thread(target=_scheduler_loop, name="content-scheduler", daemon=True)
    t.start()


# Public wrapper that guards manual updates with the same lock as the scheduler.

def manual_update(cat_ids: list[str] | None = None) -> dict:
    if not _update_lock.acquire(timeout=1):
        raise RuntimeError("uma atualização já está em andamento")
    try:
        _state["running"] = True
        if cat_ids is None:
            return update_all()
        return update_categories(cat_ids)
    finally:
        _state["running"] = False
        _update_lock.release()
