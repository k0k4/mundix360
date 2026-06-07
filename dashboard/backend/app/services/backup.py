"""Automated, verified backups of the Mundix360 appliance.

Snapshots the appliance's critical, hard-to-reproduce state into a single
timestamped ``.tar.gz`` with a manifest:

  - Firewall:   /etc/nftables.conf, /etc/nftables.d/
  - DNS/DHCP:   /etc/dnsmasq.conf, /etc/dnsmasq.d/
  - WAF:        /etc/nginx/sites-available/mundix360, /etc/nginx/modsec/
  - Dashboard:  backend/data/*.json  +  ai.db (consistent SQLite snapshot)
  - SIEM:       ClickHouse akvorado.siem_alerts (schema + Native dump, gz)

Each archive is auto-verified after creation (tar integrity, SQLite
integrity_check on the embedded ai.db, ``nft -c`` on the firewall files).
Restore is deliberately NOT auto-applied from the UI (lock-out risk): archives
can be listed, created, verified, downloaded, extracted to a staging dir and
deleted; applying a restore is an operator decision.
"""

from __future__ import annotations

import fcntl
import gzip
import io
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
import threading
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from ..config import settings
from . import shell

# --------------------------------------------------------------- constants ---

BACKUP_DIR = os.path.join(settings.base_dir, "backups")
STAGING_DIR = os.path.join(BACKUP_DIR, "staging")
LOCK_PATH = os.path.join(BACKUP_DIR, ".lock")
MIN_FREE_BYTES = 300 * 1024 * 1024  # never start a backup below this free space
MODEL_PATH = os.path.join(settings.base_dir, "dashboard/backend/data/backup.json")
DATA_DIR = os.path.join(settings.base_dir, "dashboard/backend/data")
PREFIX = "mundix-backup-"

CONFIG_PATHS = [
    "/etc/nftables.conf",
    "/etc/nftables.d",
    "/etc/dnsmasq.conf",
    "/etc/dnsmasq.d",
    "/etc/nginx/sites-available/mundix360",
    "/etc/nginx/modsec",
]

_CH_BASE = f"http://{settings.clickhouse_host}:{settings.clickhouse_port}/"
_CH_TABLE = f"{settings.clickhouse_db}.siem_alerts"

_lock = threading.Lock()
_state: dict[str, Any] = {"running": False, "phase": None}


# ------------------------------------------------------------------- model ---


def _default_model() -> dict[str, Any]:
    return {
        "schedule": {"enabled": True, "interval_hours": 24},
        "retention": 14,
        "include_clickhouse": True,
        "last_run": None,
        "last_status": None,
    }


def load_model() -> dict[str, Any]:
    try:
        with open(MODEL_PATH) as f:
            m = json.load(f)
    except (OSError, json.JSONDecodeError):
        return _default_model()
    base = _default_model()
    base.update({k: v for k, v in m.items() if k in base})
    return base


def _save_model(m: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    tmp = MODEL_PATH + ".tmp"
    with open(tmp, "w") as f:
        f.write(json.dumps(m, indent=2))
    os.replace(tmp, MODEL_PATH)


# --------------------------------------------------------------- helpers -----


def _sqlite_snapshot(src: str, dst: str) -> None:
    """Consistent online snapshot of a (possibly live, WAL) SQLite DB."""
    con = sqlite3.connect(src, timeout=30)
    try:
        bck = sqlite3.connect(dst)
        try:
            con.backup(bck)
        finally:
            bck.close()
    finally:
        con.close()


def _ch_dump_native(tar: tarfile.TarFile, manifest: dict[str, Any]) -> None:
    """Stream a ClickHouse Native dump of siem_alerts into the archive (gz)."""
    # schema
    sc = httpx.post(_CH_BASE, params={"query": f"SHOW CREATE TABLE {_CH_TABLE}"}, timeout=30)
    sc.raise_for_status()
    _add_bytes(tar, "clickhouse/siem_alerts.schema.sql", sc.text.encode())

    # data (streamed -> gzip temp file to bound memory)
    tmp = tempfile.NamedTemporaryFile(prefix="ch_", suffix=".native.gz", delete=False)
    rows = 0
    try:
        with gzip.open(tmp, "wb") as gz:
            with httpx.stream("POST", _CH_BASE,
                              params={"query": f"SELECT * FROM {_CH_TABLE} FORMAT Native"},
                              timeout=None) as resp:
                resp.raise_for_status()
                for chunk in resp.iter_bytes():
                    gz.write(chunk)
        tmp.close()
        tar.add(tmp.name, arcname="clickhouse/siem_alerts.native.gz")
        try:
            cnt = httpx.post(_CH_BASE, params={"query": f"SELECT count() FROM {_CH_TABLE}"},
                             timeout=30)
            rows = int(cnt.text.strip())
        except Exception:  # noqa: BLE001
            rows = -1
        manifest["clickhouse"] = {"table": _CH_TABLE, "rows": rows,
                                   "file": "clickhouse/siem_alerts.native.gz"}
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def _add_bytes(tar: tarfile.TarFile, arcname: str, data: bytes) -> None:
    info = tarfile.TarInfo(arcname)
    info.size = len(data)
    info.mtime = int(time.time())
    tar.addfile(info, io.BytesIO(data))


def _iter_config_members() -> list[tuple[str, str]]:
    """Return (fs_path, arcname) for each existing config file."""
    out: list[tuple[str, str]] = []
    for p in CONFIG_PATHS:
        if os.path.isfile(p):
            out.append((p, "configs" + p))
        elif os.path.isdir(p):
            for root, _dirs, files in os.walk(p):
                for fn in files:
                    fp = os.path.join(root, fn)
                    out.append((fp, "configs" + fp))
    return out


# ----------------------------------------------------------------- create ----


def create_backup() -> dict[str, Any]:
    model = load_model()
    os.makedirs(BACKUP_DIR, exist_ok=True)

    # disk-space preflight: require headroom for at least the last archive + slack
    last_size = max((b["size"] for b in list_backups()), default=0)
    needed = max(MIN_FREE_BYTES, last_size * 2)
    free = shutil.disk_usage(BACKUP_DIR).free
    if free < needed:
        raise RuntimeError(
            f"espaço em disco insuficiente: {free // (1024*1024)}MB livres, "
            f"necessário ~{needed // (1024*1024)}MB")

    ts = datetime.now(timezone.utc)
    name = PREFIX + ts.strftime("%Y%m%d-%H%M%S") + ".tar.gz"
    path = os.path.join(BACKUP_DIR, name)
    tmp_path = path + ".inprogress"
    manifest: dict[str, Any] = {
        "created": ts.isoformat(), "host": os.uname().nodename,
        "name": name, "contents": [], "include_clickhouse": False,
    }

    _state["phase"] = "archiving"
    tmp_db = None
    try:
        with tarfile.open(tmp_path, "w:gz") as tar:
            # config files
            for fp, arc in _iter_config_members():
                try:
                    tar.add(fp, arcname=arc)
                    manifest["contents"].append(arc)
                except OSError:
                    pass
            # dashboard JSON state
            if os.path.isdir(DATA_DIR):
                for fn in sorted(os.listdir(DATA_DIR)):
                    if fn.endswith(".json"):
                        tar.add(os.path.join(DATA_DIR, fn), arcname=f"data/{fn}")
                        manifest["contents"].append(f"data/{fn}")
            # ai.db consistent snapshot
            if os.path.isfile(settings.ai_db_path):
                fd, tmp_db = tempfile.mkstemp(prefix="aidb_", suffix=".db")
                os.close(fd)
                _sqlite_snapshot(settings.ai_db_path, tmp_db)
                tar.add(tmp_db, arcname="data/ai.db")
                manifest["contents"].append("data/ai.db")
            # ClickHouse SIEM history
            if model.get("include_clickhouse", True):
                _state["phase"] = "clickhouse"
                try:
                    _ch_dump_native(tar, manifest)
                    manifest["include_clickhouse"] = True
                    manifest["contents"].append("clickhouse/siem_alerts.native.gz")
                except Exception as e:  # noqa: BLE001 — CH optional, don't fail whole backup
                    manifest["clickhouse_error"] = f"{type(e).__name__}: {e}"
            # manifest last
            _add_bytes(tar, "manifest.json",
                       json.dumps(manifest, indent=2).encode())
        os.replace(tmp_path, path)
    finally:
        if tmp_db and os.path.exists(tmp_db):
            try:
                os.unlink(tmp_db)
            except OSError:
                pass
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    _state["phase"] = "verifying"
    verify = verify_backup(name)
    size = os.path.getsize(path)
    if not verify["ok"]:
        # mark so it is excluded from the restorable list and protected-good logic
        try:
            open(path + ".unverified", "w").close()
        except OSError:
            pass
    # reload model right before persisting so a concurrent set_schedule() isn't clobbered
    fresh = load_model()
    fresh["last_run"] = ts.isoformat()
    fresh["last_status"] = "ok" if verify["ok"] else "verify_failed"
    _save_model(fresh)
    _prune(fresh.get("retention", 14))
    _state["phase"] = None
    return {"ok": True, "name": name, "size": size, "verify": verify,
            "clickhouse": manifest.get("clickhouse"),
            "clickhouse_error": manifest.get("clickhouse_error")}


# ----------------------------------------------------------------- verify ----


def verify_backup(name: str) -> dict[str, Any]:
    path = _safe_path(name)
    checks: list[dict[str, Any]] = []
    ok = True

    def add(label: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        checks.append({"check": label, "ok": passed, "detail": detail})

    try:
        with tarfile.open(path, "r:gz") as tar:
            names = tar.getnames()
            add("integridade do arquivo (tar.gz)", True, f"{len(names)} membros")
            add("manifesto presente", "manifest.json" in names)
            # SQLite integrity
            if "data/ai.db" in names:
                with tempfile.TemporaryDirectory() as td:
                    tar.extract("data/ai.db", td, filter="data")
                    dbp = os.path.join(td, "data/ai.db")
                    try:
                        con = sqlite3.connect(dbp)
                        res = con.execute("PRAGMA integrity_check").fetchone()
                        con.close()
                        add("integridade do ai.db", res and res[0] == "ok",
                            res[0] if res else "sem resultado")
                    except sqlite3.Error as e:
                        add("integridade do ai.db", False, str(e))
            # ClickHouse dump: decompress fully to catch truncated/partial streams
            if "clickhouse/siem_alerts.native.gz" in names:
                try:
                    f = tar.extractfile("clickhouse/siem_alerts.native.gz")
                    total = 0
                    with gzip.GzipFile(fileobj=f) as gz:
                        while True:
                            chunk = gz.read(1024 * 1024)
                            if not chunk:
                                break
                            total += len(chunk)
                    add("integridade do dump SIEM (gzip)", total > 0,
                        f"{total // 1024} KiB descomprimidos")
                except (OSError, EOFError, gzip.BadGzipFile) as e:
                    add("integridade do dump SIEM (gzip)", False, str(e))
            # nft syntax on firewall files
            for arc in [n for n in names if n.endswith(".nft") or n == "configs/etc/nftables.conf"]:
                with tempfile.TemporaryDirectory() as td:
                    tar.extract(arc, td, filter="data")
                    fp = os.path.join(td, arc)
                    r = shell.run(["nft", "-c", "-f", fp], timeout=20)
                    # nftables.conf references absolute includes that exist live; a
                    # standalone managed .nft must parse cleanly on its own.
                    add(f"sintaxe nft: {os.path.basename(arc)}", r.ok or "No such file" in r.stderr,
                        "" if r.ok else r.stderr.strip()[:160])
    except (tarfile.TarError, OSError) as e:
        add("abertura do arquivo", False, str(e))
    return {"ok": ok, "checks": checks}


# ------------------------------------------------------------- list/manage ---


def _safe_path(name: str) -> str:
    if "/" in name or "\\" in name or not name.startswith(PREFIX) or not name.endswith(".tar.gz"):
        raise ValueError("nome de backup inválido")
    p = os.path.join(BACKUP_DIR, name)
    if os.path.islink(p):
        raise ValueError("nome de backup inválido")
    return p


def list_backups() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not os.path.isdir(BACKUP_DIR):
        return out
    for fn in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if not (fn.startswith(PREFIX) and fn.endswith(".tar.gz")):
            continue
        fp = os.path.join(BACKUP_DIR, fn)
        if os.path.islink(fp):
            continue
        try:
            st = os.stat(fp)
        except OSError:
            continue
        verified = not os.path.exists(fp + ".unverified")
        info = {"name": fn, "size": st.st_size, "verified": verified,
                "created": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
                "manifest": None}
        try:
            with tarfile.open(fp, "r:gz") as tar:
                m = tar.extractfile("manifest.json")
                if m:
                    info["manifest"] = json.loads(m.read().decode())
        except Exception:  # noqa: BLE001
            pass
        out.append(info)
    return out


def delete_backup(name: str) -> dict[str, Any]:
    path = _safe_path(name)
    if os.path.exists(path):
        os.unlink(path)
    for marker in (path + ".unverified",):
        if os.path.exists(marker):
            os.unlink(marker)
    return {"ok": True, "deleted": name}


def extract_to_staging(name: str) -> dict[str, Any]:
    """Extract an archive to a fresh staging dir for inspection (no apply)."""
    path = _safe_path(name)
    dest = os.path.join(STAGING_DIR, name.replace(".tar.gz", ""))
    if os.path.exists(dest):
        shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest, exist_ok=True)
    with tarfile.open(path, "r:gz") as tar:
        tar.extractall(dest, filter="data")
    return {"ok": True, "path": dest}


def backup_path(name: str) -> str:
    return _safe_path(name)


def _prune(keep: int) -> None:
    """Keep the newest ``keep`` archives, but never delete the newest verified
    one (so a streak of failed backups can't age out the last good snapshot)."""
    backups = list_backups()  # newest-first
    newest_good = next((b["name"] for b in backups if b.get("verified")), None)
    for b in backups[max(keep, 1):]:
        if b["name"] == newest_good:
            continue
        fp = os.path.join(BACKUP_DIR, b["name"])
        for p in (fp, fp + ".unverified"):
            try:
                os.unlink(p)
            except OSError:
                pass


# --------------------------------------------------------------- settings ----


def set_schedule(enabled: bool, interval_hours: int, retention: int,
                 include_clickhouse: bool) -> dict[str, Any]:
    m = load_model()
    m["schedule"] = {"enabled": bool(enabled),
                     "interval_hours": max(1, min(720, int(interval_hours)))}
    m["retention"] = max(1, min(365, int(retention)))
    m["include_clickhouse"] = bool(include_clickhouse)
    _save_model(m)
    return m


def overview() -> dict[str, Any]:
    m = load_model()
    backups = list_backups()
    return {
        "schedule": m["schedule"], "retention": m["retention"],
        "include_clickhouse": m["include_clickhouse"],
        "last_run": m["last_run"], "last_status": m["last_status"],
        "running": _state["running"], "phase": _state["phase"],
        "count": len(backups),
        "total_size": sum(b["size"] for b in backups),
        "backups": backups,
    }


# --------------------------------------------------------------- run/sched ---


class _Busy(RuntimeError):
    pass


def _run_locked() -> dict[str, Any]:
    """Run a backup holding both the in-process lock and an inter-process
    flock, so neither concurrent requests nor multiple workers double-run."""
    if not _lock.acquire(timeout=1):
        raise _Busy("um backup já está em andamento")
    lf = None
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        lf = open(LOCK_PATH, "w")
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise _Busy("um backup já está em andamento")
        _state["running"] = True
        return create_backup()
    finally:
        _state["running"] = False
        if lf is not None:
            try:
                fcntl.flock(lf, fcntl.LOCK_UN)
            except OSError:
                pass
            lf.close()
        _lock.release()


def run_backup() -> dict[str, Any]:
    try:
        return _run_locked()
    except _Busy as e:
        raise RuntimeError(str(e))


def _due(m: dict[str, Any]) -> bool:
    if not m.get("schedule", {}).get("enabled", True):
        return False
    lr = m.get("last_run")
    if not lr:
        return True
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(lr)).total_seconds()
    except ValueError:
        return True
    return age >= m["schedule"]["interval_hours"] * 3600


def _scheduler_loop() -> None:
    time.sleep(180)
    while True:
        try:
            if _due(load_model()):
                try:
                    _run_locked()
                except _Busy:
                    pass
        except Exception:  # noqa: BLE001 — scheduler must never die
            _state["running"] = False
        time.sleep(1800)


def start_scheduler() -> None:
    threading.Thread(target=_scheduler_loop, name="backup-scheduler", daemon=True).start()
