"""Living, contextual memory + a bidirectional journal ("bridge").

Two cooperating mechanisms, both stored in the appliance-local ``ai.db`` and
surfaced in the dashboard UI:

* **living_memory** — a single, curated, *evolving* markdown document that
  always describes how the system currently works (architecture, conventions,
  ongoing decisions). It is injected into the AI system prompt every turn, so
  the in-system AI never "forgets" the platform between conversations. It is
  bounded (size-capped) so it never makes the prompt heavy, and is maintained
  section-by-section (the AI patches one ``## section`` at a time instead of
  rewriting everything).

* **journal** — an append-only log shared between the in-system AI
  (``mundix-ai``), the external build agent (``copilot-cli``) and the human
  (``operator``). This is the communication channel: each side leaves durable
  notes the others read. Only the most recent entries are injected into the
  prompt (bounded); the full log lives in the DB / UI.

Both are treated as UNTRUSTED context in the prompt (subordinate to the
security policy) since their content may be written by the model itself.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from .memory import _conn  # shared ai.db connection (same package)

# --- bounds (keep the prompt light) ---------------------------------------
MAX_MEMORY_CHARS = 20_000          # stored cap for the living document
PROMPT_MEMORY_CHARS = 9_000        # max injected into the system prompt
JOURNAL_PROMPT_ENTRIES = 12        # recent journal entries injected
JOURNAL_KEEP = 500                 # rows retained on disk (older auto-trimmed)

AUTHORS = {"mundix-ai", "copilot-cli", "operator"}

_SEED_MEMORY = """\
# Memória viva do Mundix Security 360

> Documento curado e evolutivo. Eu (Mundix AI), o agente de build (copilot-cli)
> e o operador mantemos isto atualizado. É CONTEXTO (não sobrepõe a política de
> segurança). Atualize uma seção por vez com a ferramenta `update_system_memory`.

## Identidade
Appliance de segurança de rede (firewall + SIEM) em /opt/mundix360. Backend
FastAPI único (porta 8099, roda como root) servindo a SPA Refine/AntD (tema
escuro). Produto unificado: toda gestão e visibilidade num único ponto.

## Rede / DNS / DHCP
dnsmasq é o resolvedor DNS e servidor DHCP de produção. Configs em
/etc/dnsmasq.d/*.conf (carregadas no boot; SIGHUP NÃO relê .conf → precisa
restart). Lock de config compartilhado: network.config_lock. Zonas: lan
(ens19/192.168.0.0/24), dmz (ens20/10.0.0.0/8), iot (ens21/172.16.0.0/16),
WAN=ens18.

## Firewall
nftables. Tabela dinâmica `ip mundix_blocklist` (set blocked_ips). Firewall
gerido em /etc/nftables.d/mundix-managed.nft (substitui só inet filter + ip nat,
preservando o blocklist). Recursos: regras de filtro editáveis, port-forward
(DNAT, com anti-lockout p/ portas 22 e API), NAT de saída, aliases. Encaminha-
mento IP via /etc/sysctl.d/99-mundix-forward.conf (nunca silencioso).

## Filtro de conteúdo
Bloqueio por categoria via DNS sinkhole. services/contentcat.py baixa listas
mantidas publicamente (BlockList Project etc.) por categoria, gera
/etc/dnsmasq.d/mundix-cat-<id>.conf com address=/dom/0.0.0.0. Allowlist:
subtração exata + server=/dom/# (subdomínio sob wildcard). Aplicação
transacional (snapshot→test→restart→rollback). Agendador atualiza listas
vencidas. Bloqueio manual: services/content.py.

## Observabilidade / SIEM
ClickHouse (akvorado.siem_alerts, akvorado.flows). VictoriaMetrics (métricas),
Loki (logs), Suricata (IDS).

## Convenções
Estado em JSON sob dashboard/backend/data/. Comandos privilegiados via
services/shell.py (allowlist). Escrita atômica de config: network._atomic_write.
"""


def _now() -> float:
    return time.time()


def _uid() -> str:
    return uuid.uuid4().hex


# --- living memory ---------------------------------------------------------
def get_memory() -> dict[str, Any]:
    with _conn() as con:
        row = con.execute("SELECT * FROM living_memory WHERE id=1").fetchone()
    if not row:
        return set_memory(_SEED_MEMORY, "seed")
    return dict(row)


def set_memory(content: str, updated_by: str = "operator") -> dict[str, Any]:
    content = (content or "").strip()[:MAX_MEMORY_CHARS]
    ts = _now()
    with _conn() as con:
        con.execute(
            "INSERT INTO living_memory (id, content, updated_at, updated_by) "
            "VALUES (1, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
            "content=excluded.content, updated_at=excluded.updated_at, "
            "updated_by=excluded.updated_by",
            (content, ts, updated_by),
        )
    return {"id": 1, "content": content, "updated_at": ts, "updated_by": updated_by}


def _split_sections(md: str) -> tuple[str, list[tuple[str, str]]]:
    """Return (preamble, [(title, body_including_heading)]) split on '## '."""
    lines = md.splitlines(keepends=True)
    preamble: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    cur: list[str] | None = None
    for ln in lines:
        if ln.startswith("## "):
            if cur is not None:
                title = sections[-1][0]
                sections[-1] = (title, cur)
            title = ln[3:].strip()
            sections.append((title, []))
            cur = [ln]
        elif cur is None:
            preamble.append(ln)
        else:
            cur.append(ln)
    if cur is not None and sections:
        sections[-1] = (sections[-1][0], cur)
    return "".join(preamble), [(t, "".join(b)) for t, b in sections]


def update_section(title: str, body: str, updated_by: str = "mundix-ai") -> dict[str, Any]:
    """Replace (or append) one '## <title>' section atomically.

    Read-modify-write of the whole document happens inside a single
    BEGIN IMMEDIATE transaction so concurrent edits cannot lose each other.
    """
    title = title.strip().lstrip("#").strip()
    if not title:
        raise ValueError("título da seção é obrigatório")
    body = (body or "").strip()
    block = f"## {title}\n{body}\n"
    ts = _now()
    with _conn() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT content FROM living_memory WHERE id=1").fetchone()
        cur = row["content"] if row else _SEED_MEMORY
        preamble, sections = _split_sections(cur)
        found = False
        out = [preamble.rstrip("\n") + "\n\n"] if preamble.strip() else []
        for t, b in sections:
            if t.lower() == title.lower():
                out.append(block + "\n")
                found = True
            else:
                out.append(b.rstrip("\n") + "\n\n")
        if not found:
            out.append(block + "\n")
        content = ("".join(out).strip() + "\n")[:MAX_MEMORY_CHARS]
        con.execute(
            "INSERT INTO living_memory (id, content, updated_at, updated_by) "
            "VALUES (1, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
            "content=excluded.content, updated_at=excluded.updated_at, "
            "updated_by=excluded.updated_by",
            (content, ts, updated_by),
        )
    return {"id": 1, "content": content, "updated_at": ts, "updated_by": updated_by}


def memory_for_prompt() -> str:
    content = get_memory()["content"]
    if len(content) > PROMPT_MEMORY_CHARS:
        content = content[:PROMPT_MEMORY_CHARS] + "\n… (memória truncada; use read_system_memory)"
    return content


# --- journal (bridge) ------------------------------------------------------
def post(author: str, content: str, topic: str | None = None) -> dict[str, Any]:
    if author not in AUTHORS:
        author = "operator"
    content = (content or "").strip()[:4000]
    if not content:
        raise ValueError("mensagem vazia")
    jid = _uid()
    ts = _now()
    with _conn() as con:
        con.execute(
            "INSERT INTO journal (id, author, topic, content, created_at) "
            "VALUES (?,?,?,?,?)",
            (jid, author, (topic or "").strip()[:80] or None, content, ts),
        )
        con.execute(
            "DELETE FROM journal WHERE id NOT IN "
            "(SELECT id FROM journal ORDER BY created_at DESC, id DESC LIMIT ?)",
            (JOURNAL_KEEP,),
        )
    return {"id": jid, "author": author, "topic": topic, "content": content,
            "created_at": ts}


def recent(limit: int = 100) -> list[dict[str, Any]]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM journal ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def journal_for_prompt() -> str:
    rows = recent(JOURNAL_PROMPT_ENTRIES)
    if not rows:
        return "(sem mensagens no mural ainda)"
    rows = list(reversed(rows))  # chronological
    out = []
    for r in rows:
        when = time.strftime("%d/%m %H:%M", time.localtime(r["created_at"]))
        topic = f" «{r['topic']}»" if r["topic"] else ""
        out.append(f"- [{r['author']} · {when}]{topic} {r['content'][:400]}")
    return "\n".join(out)
