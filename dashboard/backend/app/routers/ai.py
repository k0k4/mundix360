"""AI assistant API: streaming chat, conversations, memory, audit, code-gate."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..services.ai import agent, codegate, memory

router = APIRouter(prefix="/api/ai", tags=["ai"])


class ChatIn(BaseModel):
    conversation_id: str | None = None
    message: str


class FactIn(BaseModel):
    content: str
    category: str = "note"


class ConfirmIn(BaseModel):
    change_id: str
    password: str


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
        async for sse in agent.run(cid, body.message):
            yield sse

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
