"""Placeholder masking to survive the provider's content moderation.

The AI provider (Alibaba Model Studio) refuses any request whose *text* contains
explicit sensitive terms — including adult-site domain names. Blocking such sites
is a core, legitimate function of this firewall, so we must not let moderation
stop it.

Strategy: before any text reaches the model, replace domain/URL/email tokens with
neutral placeholders (ALVO_1, ALVO_2, …). The model reasons over the placeholders
and emits them inside tool arguments; we substitute the *real* value back in before
the tool runs (and before the UI sees the action). The model therefore never sees
"xvideos.com", so moderation does not trigger, yet the real domain is still blocked.

This is per-conversation-turn state (a fresh Masker per agent run); the same real
value always maps to the same placeholder within a turn for consistency.
"""
from __future__ import annotations

import re
from typing import Any

# Domains (with a dotted TLD), optional scheme and path, and bare emails.
_TOKEN_RE = re.compile(
    r"(?:https?://)?(?:[A-Za-z0-9_-]+\.)+[A-Za-z]{2,}(?:/[^\s\"'<>]*)?",
)
_PLACEHOLDER_RE = re.compile(r"ALVO_\d+")


class Masker:
    def __init__(self) -> None:
        self._fwd: dict[str, str] = {}   # real -> placeholder
        self._rev: dict[str, str] = {}   # placeholder -> real
        self._n = 0

    @property
    def active(self) -> bool:
        return bool(self._rev)

    def mask(self, text: str | None) -> str | None:
        if not text:
            return text

        def repl(m: re.Match[str]) -> str:
            real = m.group(0)
            ph = self._fwd.get(real)
            if ph is None:
                self._n += 1
                ph = f"ALVO_{self._n}"
                self._fwd[real] = ph
                self._rev[ph] = real
            return ph

        return _TOKEN_RE.sub(repl, text)

    def unmask(self, text: str | None) -> str | None:
        if not text:
            return text
        return _PLACEHOLDER_RE.sub(
            lambda m: self._rev.get(m.group(0), m.group(0)), text
        )

    def unmask_obj(self, obj: Any) -> Any:
        """Recursively substitute placeholders back to real values in tool args."""
        if isinstance(obj, str):
            return self.unmask(obj)
        if isinstance(obj, list):
            return [self.unmask_obj(v) for v in obj]
        if isinstance(obj, dict):
            return {k: self.unmask_obj(v) for k, v in obj.items()}
        return obj

    def mask_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return a masked copy of an OpenAI-style messages list (system kept as-is)."""
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.get("role") == "system":
                out.append(m)
                continue
            mm = dict(m)
            if isinstance(mm.get("content"), str):
                mm["content"] = self.mask(mm["content"])
            tcs = mm.get("tool_calls")
            if tcs:
                new_tcs = []
                for tc in tcs:
                    tc2 = dict(tc)
                    fn = dict(tc2.get("function", {}))
                    if isinstance(fn.get("arguments"), str):
                        fn["arguments"] = self.mask(fn["arguments"])
                    tc2["function"] = fn
                    new_tcs.append(tc2)
                mm["tool_calls"] = new_tcs
            out.append(mm)
        return out
