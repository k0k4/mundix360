"""Agentic loop: streams the final answer, executes tools sequentially.

Design decisions (per security review):
- `reasoning_content` is NOT streamed or stored — only `content`.
- tool_call deltas are accumulated by index; tools run sequentially after
  finish_reason == 'tool_calls'.
- our own transparency events (tool_started/tool_result) are emitted to the UI.
- a 'propose_code_change' tool pauses the loop (awaits out-of-band password).
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from ...config import settings
from . import knowledge, memory, tools
from .mask import Masker

import re

# Longest trailing substring that could still be an *incomplete* placeholder
# (e.g. "AL", "ALVO_", "ALVO_1" which may grow to "ALVO_12"); held back until the
# placeholder is provably complete so streaming unmask never emits a partial.
_PARTIAL_PH = re.compile(r"A|AL|ALV|ALVO|ALVO_\d*")


def _held_len(s: str) -> int:
    for start in range(max(0, len(s) - 24), len(s)):
        if _PARTIAL_PH.fullmatch(s[start:]):
            return len(s) - start
    return 0

_client: AsyncOpenAI | None = None


def client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.dashscope_api_key,
            base_url=settings.ai_base_url,
            timeout=settings.ai_request_timeout,
        )
    return _client


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _is_moderation(err: Exception) -> bool:
    """True when DashScope/Model Studio content moderation rejected the turn."""
    s = str(err).lower()
    return (
        "data_inspection_failed" in s
        or "data_inspection" in s
        or "inappropriate content" in s
        or "inappropriate" in s and "content" in s
    )


# Human label per tool for the server-composed confirmation when the model's
# prose is censored by moderation but the action itself already ran.
_ACTION_LABELS = {
    "block_ip": "IP bloqueado no firewall",
    "unblock_ip": "IP desbloqueado",
    "add_port_rule": "regra de porta aplicada",
    "block_domain": "domínio adicionado à blocklist de conteúdo",
    "unblock_domain": "domínio removido da blocklist",
    "manage_zone": "zona/VLAN atualizada",
    "manage_reservation": "reserva DHCP atualizada",
    "service_action": "ação de serviço executada",
}


def _moderation_message(executed: list[str]) -> str:
    if executed:
        done = "; ".join(executed)
        return (
            "\n\n✅ Ação concluída: " + done + ".\n\n"
            "_Observação: o filtro de conteúdo da Alibaba (Model Studio) interrompeu "
            "o texto da resposta ao detectar um termo sensível, mas a operação acima "
            "foi aplicada com sucesso no sistema. Veja os cartões de ferramenta acima "
            "para os detalhes exatos._"
        )
    return (
        "\n\n⚠️ O filtro de conteúdo da Alibaba (Model Studio) bloqueou a resposta por "
        "detectar um termo sensível (ex.: nome de site adulto). Esse filtro não pode ser "
        "desativado no provedor. Você ainda pode realizar a ação: tente reformular sem "
        "citar o termo explícito, ou use o painel correspondente diretamente."
    )


def _build_messages(conversation_id: str) -> list[dict[str, Any]]:
    msgs: list[dict[str, Any]] = [
        {"role": "system", "content": knowledge.build_system_prompt()}
    ]
    msgs.extend(memory.get_messages(conversation_id, limit=60))
    return msgs


async def _stream_turn(messages: list[dict[str, Any]], masker: Masker):
    """One model call. Yields ('token', text) for content and returns the
    accumulated (content, tool_calls) via StopAsyncIteration value.

    `messages` are masked (placeholders) before being sent; streamed content is
    unmasked back to real values for the operator."""
    stream = await client().chat.completions.create(
        model=settings.ai_model,
        messages=masker.mask_messages(messages),
        tools=tools.TOOLS,
        max_tokens=settings.ai_max_tokens,
        stream=True,
        stream_options={"include_usage": True},
    )

    content_parts: list[str] = []
    tool_calls: dict[int, dict[str, Any]] = {}
    finish = None
    usage = None
    pending = ""  # raw masked content not yet safe to unmask+emit

    async for chunk in stream:
        if chunk.usage:
            usage = {
                "prompt": chunk.usage.prompt_tokens,
                "completion": chunk.usage.completion_tokens,
            }
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        delta = choice.delta
        if choice.finish_reason:
            finish = choice.finish_reason
        # final answer text only (never reasoning_content)
        if getattr(delta, "content", None):
            content_parts.append(delta.content)
            pending += delta.content
            hold = _held_len(pending)
            safe, pending = pending[: len(pending) - hold], pending[len(pending) - hold:]
            if safe:
                yield ("token", masker.unmask(safe))
        # accumulate tool calls by index
        for tc in getattr(delta, "tool_calls", None) or []:
            slot = tool_calls.setdefault(
                tc.index, {"id": None, "name": "", "arguments": ""}
            )
            if tc.id:
                slot["id"] = tc.id
            if tc.function and tc.function.name:
                slot["name"] = tc.function.name
            if tc.function and tc.function.arguments:
                slot["arguments"] += tc.function.arguments

    if pending:
        yield ("token", masker.unmask(pending))

    ordered = [tool_calls[i] for i in sorted(tool_calls)]
    yield ("_final", {"content": "".join(content_parts), "tool_calls": ordered,
                      "finish": finish, "usage": usage})


async def run(conversation_id: str, user_message: str) -> AsyncIterator[str]:
    """Async generator of SSE strings for one user message."""
    memory.add_message(conversation_id, "user", content=user_message)
    memory.touch_conversation(conversation_id)
    messages = _build_messages(conversation_id)

    masker = Masker()
    executed: list[str] = []  # human labels of operational actions applied this turn

    try:
        for _ in range(settings.ai_max_tool_iters):
            content = ""
            tool_calls: list[dict[str, Any]] = []
            usage = None
            finish = None

            async for kind, payload in _stream_turn(messages, masker):
                if kind == "token":
                    yield _sse("token", {"text": payload})
                elif kind == "_final":
                    # model output is in placeholder space -> restore real values
                    content = masker.unmask(payload["content"])
                    tool_calls = payload["tool_calls"]
                    for tc in tool_calls:
                        tc["arguments"] = masker.unmask(tc.get("arguments") or "")
                    finish = payload["finish"]
                    usage = payload["usage"]

            if usage:
                yield _sse("usage", usage)

            # No tools requested -> final answer
            if not tool_calls:
                memory.add_message(conversation_id, "assistant", content=content)
                yield _sse("done", {})
                return

            # Drop malformed tool calls (missing id/name) so we never send the
            # provider an invalid follow-up request that would error the turn.
            tool_calls = [
                tc for tc in tool_calls
                if tc.get("id") and tc.get("name")
            ]
            if not tool_calls:
                if content:
                    memory.add_message(conversation_id, "assistant", content=content)
                yield _sse("done", {})
                return

            # Persist + append the assistant message carrying tool_calls
            assistant_tcs = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"] or "{}"},
                }
                for tc in tool_calls
            ]
            memory.add_message(conversation_id, "assistant", content=content or None,
                               tool_calls=assistant_tcs)
            messages.append({"role": "assistant", "content": content or None,
                             "tool_calls": assistant_tcs})

            paused = False
            # Execute sequentially (live firewall: avoid concurrent state changes)
            for tc in tool_calls:
                name = tc["name"]
                try:
                    args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                except json.JSONDecodeError:
                    args = {}
                yield _sse("tool_started", {"name": name, "arguments": args})

                result = tools.dispatch(name, args, conversation_id)

                event = result.pop("_event", None) if isinstance(result, dict) else None
                if event:
                    yield _sse(event["type"], event["data"])

                yield _sse("tool_result", {"name": name, "result": result})

                # Track successfully applied operational actions so we can confirm
                # them even if the model's summary is later censored by moderation.
                if (
                    name in _ACTION_LABELS
                    and isinstance(result, dict)
                    and not result.get("error")
                    and not result.get("blocked")
                ):
                    executed.append(_ACTION_LABELS[name])

                tool_msg_content = json.dumps(result, ensure_ascii=False)
                memory.add_message(conversation_id, "tool", content=tool_msg_content,
                                   tool_call_id=tc["id"], name=name)
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                                 "name": name, "content": tool_msg_content})

                if name in tools.SPECIAL_TOOLS and isinstance(result, dict) and result.get("pending"):
                    paused = True

            if paused:
                # Let the model summarise, then stop and wait for the operator.
                async for kind, payload in _stream_turn(messages, masker):
                    if kind == "token":
                        yield _sse("token", {"text": payload})
                    elif kind == "_final" and payload["content"]:
                        memory.add_message(conversation_id, "assistant",
                                           content=masker.unmask(payload["content"]))
                yield _sse("awaiting_confirmation", {})
                yield _sse("done", {})
                return

        yield _sse("token", {"text": "\n\n[Limite de iterações de ferramentas atingido.]"})
        yield _sse("done", {})
    except Exception as e:
        from . import safety

        if _is_moderation(e):
            msg = _moderation_message(executed)
            # Persist a clean note (never the censored content) so history stays usable.
            memory.add_message(conversation_id, "assistant", content=msg.strip())
            yield _sse("token", {"text": msg})
            yield _sse("done", {})
            return

        yield _sse("error", {"message": safety.redact(str(e)) or "erro no agente"})
        yield _sse("done", {})
