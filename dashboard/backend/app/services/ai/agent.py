"""Agentic loop: streams the final answer, executes tools sequentially.

Design decisions (per security review):
- `reasoning_content` is NOT streamed or stored — only `content`.
- tool_call deltas are accumulated by index; tools run sequentially after
  finish_reason == 'tool_calls'.
- our own transparency events (tool_started/tool_result) are emitted to the UI.
- a 'propose_code_change' tool pauses the loop (awaits out-of-band password).
"""
from __future__ import annotations

import itertools
import time
import json
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from ...config import settings
from . import config_store, knowledge, memory, tools
from .mask import Masker, NullMasker

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

_clients: dict[tuple, AsyncOpenAI] = {}

# Stuck-loop guard: how many times the *same tool call producing the same
# result* may occur in a turn before we stop and force a final answer. This is
# not a cap on productive work — a call that returns a different result each
# time (legitimate polling/progress) never trips it; only a call that keeps
# returning the same thing (a failing/looping tool) does. It catches both
# consecutive (A,A,A,A) and alternating (A,B,A,B,...) non-progressing loops.
_STUCK_REPEATS = 4

# Absolute wall-clock backstop for a single turn (seconds). With iterations
# unlimited, this is the final safety net against a model that loops forever
# while always producing *different* output (so the stuck guard never fires).
# Generous on purpose: real tasks finish well under this.
_MAX_RUN_SECONDS = 1800


def client(cfg: dict[str, Any]) -> AsyncOpenAI:
    """Return an AsyncOpenAI client for the effective provider config, cached by
    (api_key, base_url, timeout). New config -> new client; the small cache is
    capped so stale clients don't accumulate unboundedly."""
    key = (cfg["api_key"], cfg["base_url"], cfg["request_timeout"])
    c = _clients.get(key)
    if c is None:
        if len(_clients) > 4:
            _clients.clear()
        c = AsyncOpenAI(
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
            timeout=cfg["request_timeout"],
        )
        _clients[key] = c
    return c


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


def _build_messages(conversation_id: str, context: str | None = None) -> list[dict[str, Any]]:
    msgs: list[dict[str, Any]] = [
        {"role": "system", "content": knowledge.build_system_prompt(context=context)}
    ]
    msgs.extend(memory.get_messages(conversation_id, limit=60))
    return msgs


def _ensure_json_tool_args(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Guarantee every assistant tool_call carries a valid JSON-object string in
    ``function.arguments``. Some providers (e.g. DashScope/Qwen code models) reject
    requests where a replayed tool call has empty or non-JSON arguments — which
    happens for our zero-parameter tools (status/update calls). Normalizes to '{}'
    without mutating the original history dicts."""
    fixed: list[dict[str, Any]] = []
    for m in messages:
        tcs = m.get("tool_calls")
        if not tcs:
            fixed.append(m)
            continue
        new_tcs = []
        changed = False
        for tc in tcs:
            fn = tc.get("function") or {}
            args = fn.get("arguments")
            valid = isinstance(args, str) and args.strip() != ""
            if valid:
                try:
                    json.loads(args)
                except (ValueError, TypeError):
                    valid = False
            if not valid:
                tc = {**tc, "function": {**fn, "arguments": "{}"}}
                changed = True
            new_tcs.append(tc)
        fixed.append({**m, "tool_calls": new_tcs} if changed else m)
    return fixed


async def _stream_turn(messages: list[dict[str, Any]], masker: Masker, cfg: dict[str, Any],
                       tools_enabled: bool = True):
    """One model call. Yields ('token', text) for content and returns the
    accumulated (content, tool_calls) via a '_final' item.

    `messages` are masked (placeholders) before being sent; streamed content is
    unmasked back to real values for the operator. When ``tools_enabled`` is
    False the model is forced to answer in prose (no further tool calls)."""
    kwargs: dict[str, Any] = {}
    if tools_enabled:
        kwargs["tools"] = tools.TOOLS
    stream = await client(cfg).chat.completions.create(
        model=cfg["model"],
        messages=_ensure_json_tool_args(masker.mask_messages(messages)),
        max_tokens=cfg["max_tokens"],
        temperature=cfg["temperature"],
        stream=True,
        stream_options={"include_usage": True},
        **kwargs,
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


async def run(conversation_id: str, user_message: str, context: str | None = None) -> AsyncIterator[str]:
    """Async generator of SSE strings for one user message."""
    memory.add_message(conversation_id, "user", content=user_message)
    memory.touch_conversation(conversation_id)

    cfg = config_store.effective()
    messages = _build_messages(conversation_id, context)

    masker: Masker = Masker() if cfg["masking_enabled"] else NullMasker()
    executed: list[str] = []  # human labels of operational actions applied this turn

    try:
        # max_tool_iters <= 0 means "no limit" — iterate until the model stops
        # requesting tools. A stuck-loop guard (below) still prevents a genuine
        # infinite loop on a repeating, non-progressing tool call.
        max_iters = cfg["max_tool_iters"]
        loop = itertools.count() if max_iters <= 0 else range(max_iters)
        stuck_counts: dict[str, int] = {}
        error_counts: dict[str, int] = {}
        started = time.monotonic()
        for _ in loop:
            if time.monotonic() - started > _MAX_RUN_SECONDS:
                break
            content = ""
            tool_calls: list[dict[str, Any]] = []
            usage = None
            finish = None

            async for kind, payload in _stream_turn(messages, masker, cfg):
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

            # Signature of the requested batch (names + args); combined with the
            # results below to detect non-progressing loops.
            call_sig = json.dumps(
                [[tc.get("name"), tc.get("arguments") or ""] for tc in tool_calls],
                ensure_ascii=False, sort_keys=True,
            )

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
            batch_results: list[Any] = []
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
                batch_results.append(result)

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
                async for kind, payload in _stream_turn(messages, masker, cfg):
                    if kind == "token":
                        yield _sse("token", {"text": payload})
                    elif kind == "_final" and payload["content"]:
                        memory.add_message(conversation_id, "assistant",
                                           content=masker.unmask(payload["content"]))
                yield _sse("awaiting_confirmation", {})
                yield _sse("done", {})
                return

            # Stuck-loop guard: a call that keeps returning the SAME result is not
            # making progress. Key on call + result so legitimate polling (same
            # call, changing result) is never interrupted; only a repeating,
            # non-progressing call (incl. alternating A,B,A,B) trips this.
            try:
                result_sig = json.dumps(batch_results, ensure_ascii=False,
                                        sort_keys=True, default=str)
            except Exception:
                result_sig = repr(batch_results)
            sig = call_sig + "::" + result_sig
            stuck_counts[sig] = stuck_counts.get(sig, 0) + 1
            if stuck_counts[sig] >= _STUCK_REPEATS:
                break

            # Secondary guard: a tool batch that keeps FAILING with the same error
            # is not progressing even if the model varies its arguments each time
            # (e.g. repeatedly calling propose_code_change with a missing 'path').
            # Keyed on the error payload alone so legitimate, succeeding calls and
            # genuine polling (changing/non-error results) never trip it.
            batch_errors = [
                r.get("error") for r in batch_results
                if isinstance(r, dict) and r.get("error")
            ]
            if batch_errors and len(batch_errors) == len(batch_results):
                err_sig = json.dumps(batch_errors, ensure_ascii=False, sort_keys=True)
                error_counts[err_sig] = error_counts.get(err_sig, 0) + 1
                if error_counts[err_sig] >= _STUCK_REPEATS:
                    break

        # Reached only if the stuck-loop guard fired or a finite iteration limit
        # was configured and exhausted. Force one final answer with tools disabled
        # so the operator gets a useful summary instead of a dead-end notice.
        messages.append({
            "role": "user",
            "content": ("Responda agora, de forma objetiva, com base nas "
                        "informações já coletadas — não chame mais ferramentas."),
        })
        final = ""
        async for kind, payload in _stream_turn(messages, masker, cfg, tools_enabled=False):
            if kind == "token":
                yield _sse("token", {"text": payload})
            elif kind == "_final":
                final = masker.unmask(payload["content"])
        if final:
            memory.add_message(conversation_id, "assistant", content=final)
        else:
            note = ("\n\n[Não consegui concluir automaticamente — uma ferramenta "
                    "parece estar repetindo sem progresso. Tente reformular o pedido.]")
            memory.add_message(conversation_id, "assistant", content=note.strip())
            yield _sse("token", {"text": note})
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
