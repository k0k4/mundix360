"""AI assistant API: streaming chat, conversations, memory, audit, code-gate."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..services.ai import agent, codegate, config_store, memory, livingmemory

router = APIRouter(prefix="/api/ai", tags=["ai"])

# Seconds of silence after which we emit an SSE comment heartbeat, so reverse
# proxies (nginx) and the browser don't drop an idle connection while the model
# is "thinking" or a slow tool runs. SSE comment lines (":") are ignored by the
# client parser, so they never appear in the transcript.
_HEARTBEAT_SECONDS = 15.0


class ChatIn(BaseModel):
    conversation_id: str | None = None
    message: str
    context: str | None = None


class FactIn(BaseModel):
    content: str
    category: str = "note"


class ConfirmIn(BaseModel):
    change_id: str
    password: str


class ConfigIn(BaseModel):
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    request_timeout: int | None = None
    max_tokens: int | None = None
    max_tool_iters: int | None = None
    temperature: float | None = None
    masking_enabled: bool | None = None
    custom_instructions: str | None = None
    master_password: str | None = None
    # current master password, required to change sensitive fields once one is set
    master_password_current: str | None = None


class TestIn(BaseModel):
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None


@router.post("/chat/stream")
async def chat_stream(body: ChatIn):
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="mensagem vazia")
    cid = body.conversation_id
    if not cid or not memory.get_conversation(cid):
        title = body.message.strip()[:48]
        cid = memory.create_conversation(title)["id"]

    async def gen():
        # tell the client which conversation this is (esp. for new ones)
        yield f"event: meta\ndata: {{\"conversation_id\": \"{cid}\"}}\n\n"

        # Pump the agent's SSE strings through a queue so we can interleave
        # heartbeat comments during idle gaps (model thinking / slow tools)
        # without blocking on the agent generator.
        queue: asyncio.Queue = asyncio.Queue()
        _DONE = object()

        async def pump():
            try:
                async for sse in agent.run(cid, body.message, context=body.context):
                    await queue.put(sse)
            except Exception as e:  # never wedge the stream on an agent crash
                from ..services.ai import safety
                msg = safety.redact(str(e)) or "erro no agente"
                await queue.put(f"event: error\ndata: {{\"message\": \"{msg}\"}}\n\n")
                await queue.put("event: done\ndata: {}\n\n")
            finally:
                await queue.put(_DONE)

        task = asyncio.create_task(pump())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # SSE comment keepalive
                    continue
                if item is _DONE:
                    break
                yield item
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- conversations ---------------------------------------------------------
@router.get("/conversations")
def conversations():
    return {"conversations": memory.list_conversations()}


@router.post("/conversations")
def new_conversation():
    return memory.create_conversation()


class RenameIn(BaseModel):
    title: str


@router.patch("/conversations/{cid}")
def rename_conversation(cid: str, body: RenameIn):
    conv = memory.rename_conversation(cid, body.title)
    if not conv:
        raise HTTPException(status_code=404, detail="conversa não encontrada ou título vazio")
    return conv


@router.get("/conversations/{cid}")
def conversation(cid: str):
    conv = memory.get_conversation(cid)
    if not conv:
        raise HTTPException(status_code=404, detail="conversa não encontrada")
    return {"conversation": conv, "messages": memory.get_messages(cid, limit=500)}


@router.delete("/conversations/{cid}")
def remove_conversation(cid: str):
    memory.delete_conversation(cid)
    return {"ok": True}


# --- memory / facts --------------------------------------------------------
@router.get("/memory")
def list_memory():
    return {"facts": memory.list_facts()}


@router.post("/memory")
def add_memory(body: FactIn):
    return memory.add_fact(body.content, body.category)


@router.delete("/memory/{fid}")
def del_memory(fid: str):
    memory.delete_fact(fid)
    return {"ok": True}


# --- living memory + journal (the AI bridge) -------------------------------
class MemoryIn(BaseModel):
    content: str
    updated_by: str = "operator"


class JournalIn(BaseModel):
    message: str
    author: str = "operator"
    topic: str | None = None


@router.get("/living-memory")
def get_living_memory():
    return livingmemory.get_memory()


@router.put("/living-memory")
def put_living_memory(body: MemoryIn):
    return livingmemory.set_memory(body.content, body.updated_by or "operator")


@router.get("/journal")
def get_journal(limit: int = 100):
    return {"entries": livingmemory.recent(min(limit, 200))}


@router.post("/journal")
def post_journal(body: JournalIn):
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="mensagem vazia")
    try:
        return livingmemory.post(body.author or "operator", body.message, body.topic)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/audit")
def audit():
    return {"audit": memory.list_audit()}


# --- code-change gate ------------------------------------------------------
@router.get("/code-changes")
def pending_changes():
    return {"pending": codegate.list_pending()}


@router.post("/code-change/confirm")
def confirm_change(body: ConfirmIn, request: Request):
    try:
        result = codegate.confirm(body.change_id, body.password)
    except PermissionError as e:
        memory.audit("code_change_confirm", {"change_id": body.change_id}, "denied",
                     str(e), actor=request.client.host if request.client else "unknown")
        raise HTTPException(status_code=403, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    memory.audit("code_change_confirm", {"change_id": body.change_id, "path": result["path"]},
                 "ok", f"committed={result.get('committed')} {result.get('commit')}",
                 actor=request.client.host if request.client else "unknown")
    return result


# --- AI configuration ------------------------------------------------------
@router.get("/config")
def get_config():
    return config_store.public_config()


@router.put("/config")
def put_config(body: ConfigIn, request: Request):
    updates = body.model_dump(exclude_none=True)
    updates.pop("master_password_current", None)
    if not updates:
        return config_store.public_config()

    # Sensitive changes require the current master password once one is configured.
    sensitive = set(updates) & config_store.SENSITIVE_KEYS
    if sensitive and config_store.master_password_set():
        if not config_store.verify_master_password(body.master_password_current or ""):
            memory.audit("ai_config_update", {"keys": sorted(sensitive)}, "denied",
                         "senha mestra atual inválida",
                         actor=request.client.host if request.client else "unknown")
            raise HTTPException(
                status_code=403,
                detail="senha mestra atual obrigatória para alterar campos sensíveis",
            )

    try:
        changed = config_store.apply_updates(updates)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    memory.audit("ai_config_update", {"keys": changed}, "ok",
                 "configuração da IA atualizada",
                 actor=request.client.host if request.client else "unknown")
    return config_store.public_config()


@router.post("/config/test")
async def test_config(body: TestIn):
    """Minimal, neutral connectivity check against a provider. Never persists,
    uses no tools/memory/context, short and small."""
    from openai import AsyncOpenAI

    eff = config_store.effective()
    base_url = body.base_url or eff["base_url"]
    model = body.model or eff["model"]
    api_key = body.api_key or eff["api_key"]
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        raise HTTPException(status_code=400, detail="base_url inválida")
    if not api_key:
        raise HTTPException(status_code=400, detail="chave de API ausente")

    client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=20)
    try:
        r = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with OK."}],
            max_tokens=4,
        )
        reply = (r.choices[0].message.content or "").strip() if r.choices else ""
        return {"ok": True, "model": model, "reply": reply[:40]}
    except Exception as e:  # noqa: BLE001
        from ..services.ai import safety

        return {"ok": False, "error": safety.redact(str(e))[:300]}
    finally:
        try:
            await client.close()
        except Exception:
            pass
