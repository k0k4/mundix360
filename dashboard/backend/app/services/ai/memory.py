"""Persistent, evolutive memory + conversation store for the AI assistant.

SQLite-backed (WAL), appliance-local. Holds:
- conversations / messages  -> chat history across sessions
- facts                     -> evolutive memory (typed, timestamped, *untrusted*)
- audit                     -> immutable-ish audit trail of every tool action
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ...config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    title       TEXT,
    created_at  REAL,
    updated_at  REAL
);
CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT,
    role            TEXT,
    content         TEXT,
    tool_calls      TEXT,
    tool_call_id    TEXT,
    name            TEXT,
    created_at      REAL
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS facts (
    id          TEXT PRIMARY KEY,
    category    TEXT,
    content     TEXT,
    created_at  REAL,
    updated_at  REAL
);
CREATE INDEX IF NOT EXISTS idx_facts_cat ON facts(category, updated_at);

CREATE TABLE IF NOT EXISTS audit (
    id          TEXT PRIMARY KEY,
    conversation_id TEXT,
    tool        TEXT,
    arguments   TEXT,
    status      TEXT,
    summary     TEXT,
    actor       TEXT,
    created_at  REAL
);
CREATE INDEX IF NOT EXISTS idx_audit_time ON audit(created_at);

CREATE TABLE IF NOT EXISTS ai_config (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  REAL
);

CREATE TABLE IF NOT EXISTS living_memory (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    content     TEXT,
    updated_at  REAL,
    updated_by  TEXT
);

CREATE TABLE IF NOT EXISTS journal (
    id          TEXT PRIMARY KEY,
    author      TEXT,
    topic       TEXT,
    content     TEXT,
    created_at  REAL
);
CREATE INDEX IF NOT EXISTS idx_journal_time ON journal(created_at);
"""

FACT_CATEGORIES = {"system", "preference", "incident", "exclusion", "note"}


def _now() -> float:
    return time.time()


def _uid() -> str:
    return uuid.uuid4().hex


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    Path(settings.ai_db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(settings.ai_db_path, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA busy_timeout=8000;")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db() -> None:
    with _conn() as con:
        con.executescript(_SCHEMA)


# --- conversations ---------------------------------------------------------
def create_conversation(title: str = "Nova conversa") -> dict[str, Any]:
    cid = _uid()
    ts = _now()
    with _conn() as con:
        con.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?,?,?,?)",
            (cid, title, ts, ts),
        )
    return {"id": cid, "title": title, "created_at": ts, "updated_at": ts}


def list_conversations(limit: int = 100) -> list[dict[str, Any]]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        convs = [dict(r) for r in rows]
        for c in convs:
            prev = con.execute(
                "SELECT content FROM messages WHERE conversation_id=? AND content IS NOT NULL "
                "AND role IN ('user','assistant') ORDER BY created_at DESC LIMIT 1",
                (c["id"],),
            ).fetchone()
            c["preview"] = (prev["content"][:120] if prev and prev["content"] else "")
    return convs


def rename_conversation(cid: str, title: str) -> dict[str, Any] | None:
    title = (title or "").strip()[:120]
    if not title:
        return None
    with _conn() as con:
        cur = con.execute(
            "UPDATE conversations SET title=?, updated_at=? WHERE id=?",
            (title, _now(), cid),
        )
        if cur.rowcount == 0:
            return None
    return get_conversation(cid)


def get_conversation(cid: str) -> dict[str, Any] | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
    return dict(row) if row else None


def delete_conversation(cid: str) -> None:
    with _conn() as con:
        con.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
        con.execute("DELETE FROM conversations WHERE id=?", (cid,))


def touch_conversation(cid: str, title: str | None = None) -> None:
    with _conn() as con:
        if title:
            con.execute(
                "UPDATE conversations SET updated_at=?, title=? WHERE id=?",
                (_now(), title, cid),
            )
        else:
            con.execute(
                "UPDATE conversations SET updated_at=? WHERE id=?", (_now(), cid)
            )


# --- messages --------------------------------------------------------------
def add_message(
    conversation_id: str,
    role: str,
    content: str | None = None,
    tool_calls: list[dict] | None = None,
    tool_call_id: str | None = None,
    name: str | None = None,
) -> None:
    with _conn() as con:
        con.execute(
            "INSERT INTO messages (id, conversation_id, role, content, tool_calls, "
            "tool_call_id, name, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                _uid(),
                conversation_id,
                role,
                content,
                json.dumps(tool_calls) if tool_calls else None,
                tool_call_id,
                name,
                _now(),
            ),
        )


def get_messages(conversation_id: str, limit: int = 200) -> list[dict[str, Any]]:
    """Return messages as OpenAI-compatible dicts (oldest first)."""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at ASC "
            "LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        msg: dict[str, Any] = {"role": r["role"]}
        if r["content"] is not None:
            msg["content"] = r["content"]
        if r["tool_calls"]:
            msg["tool_calls"] = json.loads(r["tool_calls"])
            msg.setdefault("content", None)
        if r["tool_call_id"]:
            msg["tool_call_id"] = r["tool_call_id"]
        if r["name"]:
            msg["name"] = r["name"]
        out.append(msg)
    return out


# --- facts (evolutive memory) ---------------------------------------------
def add_fact(content: str, category: str = "note") -> dict[str, Any]:
    if category not in FACT_CATEGORIES:
        category = "note"
    fid = _uid()
    ts = _now()
    with _conn() as con:
        con.execute(
            "INSERT INTO facts (id, category, content, created_at, updated_at) "
            "VALUES (?,?,?,?,?)",
            (fid, category, content, ts, ts),
        )
    return {"id": fid, "category": category, "content": content, "updated_at": ts}


def list_facts(limit: int = 200) -> list[dict[str, Any]]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM facts ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def delete_fact(fid: str) -> None:
    with _conn() as con:
        con.execute("DELETE FROM facts WHERE id=?", (fid,))


# --- audit -----------------------------------------------------------------
def audit(
    tool: str,
    arguments: dict[str, Any],
    status: str,
    summary: str,
    conversation_id: str | None = None,
    actor: str = "ai",
) -> None:
    with _conn() as con:
        con.execute(
            "INSERT INTO audit (id, conversation_id, tool, arguments, status, summary, "
            "actor, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                _uid(),
                conversation_id,
                tool,
                json.dumps(arguments, ensure_ascii=False)[:4000],
                status,
                summary[:2000],
                actor,
                _now(),
            ),
        )


def list_audit(limit: int = 200) -> list[dict[str, Any]]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM audit ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
