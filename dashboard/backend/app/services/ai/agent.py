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


def _build_messages(conversation_id: str) -> list[dict[str, Any]]:
    msgs: list[dict[str, Any]] = [
        {"role": "system", "content": knowledge.build_system_prompt()}
    ]
    msgs.extend(memory.get_messages(conversation_id, limit=60))
    return msgs


async def _stream_turn(messages: list[dict[str, Any]]):
    """One model call. Yields ('token', text) for content and returns the
    accumulated (content, tool_calls) via StopAsyncIteration value."""
    stream = await client().chat.completions.create(
        model=settings.ai_model,
        messages=messages,
        tools=tools.TOOLS,
        max_tokens=settings.ai_max_tokens,
        stream=True,
        stream_options={"include_usage": True},
    )

    content_parts: list[str] = []
    tool_calls: dict[int, dict[str, Any]] = {}
    finish = None
    usage = None

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
            yield ("token", delta.content)
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

    ordered = [tool_calls[i] for i in sorted(tool_calls)]
    yield ("_final", {"content": "".join(content_parts), "tool_calls": ordered,
                      "finish": finish, "usage": usage})


async def run(conversation_id: str, user_message: str) -> AsyncIterator[str]:
    """Async generator of SSE strings for one user message."""
    memory.add_message(conversation_id, "user", content=user_message)
    memory.touch_conversation(conversation_id)
    messages = _build_messages(conversation_id)

    try:
        for _ in range(settings.ai_max_tool_iters):
            content = ""
            tool_calls: list[dict[str, Any]] = []
            usage = None
            finish = None

            async for kind, payload in _stream_turn(messages):
                if kind == "token":
                    yield _sse("token", {"text": payload})
                elif kind == "_final":
                    content = payload["content"]
                    tool_calls = payload["tool_calls"]
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

                tool_msg_content = json.dumps(result, ensure_ascii=False)
                memory.add_message(conversation_id, "tool", content=tool_msg_content,
                                   tool_call_id=tc["id"], name=name)
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                                 "name": name, "content": tool_msg_content})

                if name in tools.SPECIAL_TOOLS and isinstance(result, dict) and result.get("pending"):
                    paused = True

            if paused:
                # Let the model summarise, then stop and wait for the operator.
                async for kind, payload in _stream_turn(messages):
                    if kind == "token":
                        yield _sse("token", {"text": payload})
                    elif kind == "_final" and payload["content"]:
                        memory.add_message(conversation_id, "assistant",
                                           content=payload["content"])
                yield _sse("awaiting_confirmation", {})
                yield _sse("done", {})
                return

        yield _sse("token", {"text": "\n\n[Limite de iterações de ferramentas atingido.]"})
        yield _sse("done", {})
    except Exception as e:
        from . import safety
        yield _sse("error", {"message": safety.redact(str(e)) or "erro no agente"})
        yield _sse("done", {})
