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

# Domains (with a dotted TLD), optional scheme and path, and bare emails. The
# negative lookahead after the TLD prevents matching a fragment of a larger code
# identifier (e.g. the "settings.ai" inside "settings.ai_max_tokens").
_TOKEN_RE = re.compile(
    r"(?:https?://)?(?:[A-Za-z0-9_-]+\.)+[A-Za-z]{2,}(?![A-Za-z0-9_])(?:/[^\s\"'<>]*)?",
)
_PLACEHOLDER_RE = re.compile(r"ALVO_\d+")

# File/code extensions and config suffixes that must NEVER be treated as a
# blockable domain. Without this, the masker mangled every filename and import
# path (e.g. "interfaces.tsx" -> "ALVO_57"), blinding the model to the codebase
# it is supposed to read and edit. Lower-cased, compared against the final label.
_CODE_EXT = frozenset({
    "ts", "tsx", "js", "jsx", "mjs", "cjs", "py", "pyc", "pyi", "go", "rs",
    "java", "kt", "c", "h", "cpp", "cc", "hpp", "rb", "php", "cs", "swift",
    "json", "yaml", "yml", "toml", "ini", "cfg", "conf", "config", "env", "lock",
    "md", "markdown", "rst", "txt", "csv", "tsv", "log", "sql", "db", "sqlite",
    "sh", "bash", "zsh", "ps1", "bat", "make", "mk", "dockerfile",
    "html", "htm", "css", "scss", "sass", "less", "xml", "svg", "vue",
    "png", "jpg", "jpeg", "gif", "webp", "ico", "pdf", "zip", "tar", "gz",
    "service", "timer", "socket", "target", "mount", "nft", "rules", "tpl",
})

# A token is only treated as a blockable domain if its final label is a real
# public TLD. This is the reliable way to tell "xvideos.com" (mask) apart from
# dotted code identifiers like "app.config" or "settings.ai_max_tokens" (keep) —
# the previous heuristic masked both, corrupting the model's view of the code.
# Common gTLDs plus the full ISO-3166 ccTLD set.
_TLD = frozenset({
    "com", "net", "org", "info", "biz", "io", "co", "ai", "app", "dev", "xyz",
    "top", "site", "online", "store", "shop", "club", "vip", "live", "tv",
    "me", "cc", "gg", "pro", "name", "mobi", "asia", "tech", "cloud", "page",
    "gov", "edu", "mil", "int", "eu", "win", "men", "stream", "download", "loan",
    "work", "link", "fun", "icu", "cyou", "sbs", "lol", "buzz", "cam", "porn",
    "sex", "xxx", "adult", "casino", "bet", "poker", "news", "blog", "wiki",
    # ISO-3166 ccTLDs
    "ac", "ad", "ae", "af", "ag", "al", "am", "ao", "aq", "ar", "as", "at",
    "au", "aw", "ax", "az", "ba", "bb", "bd", "be", "bf", "bg", "bh", "bi",
    "bj", "bm", "bn", "bo", "br", "bs", "bt", "bw", "by", "bz", "ca", "cd",
    "cf", "cg", "ch", "ci", "ck", "cl", "cm", "cn", "cr", "cu", "cv", "cw",
    "cx", "cy", "cz", "de", "dj", "dk", "dm", "do", "dz", "ec", "ee", "eg",
    "er", "es", "et", "fi", "fj", "fk", "fm", "fo", "fr", "ga", "gd", "ge",
    "gf", "gh", "gi", "gl", "gm", "gn", "gp", "gq", "gr", "gt", "gu", "gw",
    "gy", "hk", "hn", "hr", "ht", "hu", "id", "ie", "il", "im", "in", "iq",
    "ir", "is", "it", "je", "jm", "jo", "jp", "ke", "kg", "kh", "ki", "km",
    "kn", "kp", "kr", "kw", "ky", "kz", "la", "lb", "lc", "li", "lk", "lr",
    "ls", "lt", "lu", "lv", "ly", "ma", "mc", "md", "mg", "mk", "ml",
    "mm", "mn", "mo", "mp", "mq", "mr", "ms", "mt", "mu", "mv", "mw", "mx",
    "my", "mz", "na", "nc", "ne", "nf", "ng", "ni", "nl", "no", "np", "nr",
    "nu", "nz", "om", "pa", "pe", "pf", "pg", "ph", "pk", "pl", "pm", "pn",
    "pr", "ps", "pt", "pw", "py", "qa", "re", "ro", "rs", "ru", "rw", "sa",
    "sb", "sc", "sd", "se", "sg", "sh", "si", "sk", "sl", "sm", "sn", "so",
    "sr", "ss", "st", "sv", "sx", "sy", "sz", "tc", "td", "tg", "th", "tj",
    "tk", "tl", "tm", "tn", "to", "tr", "tt", "tw", "tz", "ua", "ug", "uk",
    "us", "uy", "uz", "va", "vc", "ve", "vg", "vi", "vn", "vu", "wf", "ws",
    "ye", "za", "zm", "zw",
})

# Tools whose arguments may legitimately carry a user-typed blockable domain and
# therefore still need masking on the way to the provider. Every other tool
# (read_file, list_dir, search_code, run_shell, propose_code_*, ...) carries code
# and file paths that must reach the model verbatim.
_DOMAIN_TOOLS = frozenset({"block_domain", "unblock_domain"})


def _maskable(token: str) -> bool:
    """True only for genuine blockable domains/URLs/emails — never for code,
    file paths, module imports or version strings."""
    has_scheme = token.startswith(("http://", "https://"))
    # A slash without a scheme means a filesystem path (e.g. "src/app.py"); the
    # regex only ever captures the trailing "app.py", but be defensive anyway.
    if "/" in token and not has_scheme:
        return False
    # Extract the host (drop scheme and any path/query) to inspect its TLD.
    host = token
    if has_scheme:
        host = token.split("://", 1)[1]
    host = host.split("/", 1)[0].split("@")[-1]
    # Hostnames don't allow underscores; their presence means a code identifier.
    if "_" in host or "." not in host:
        return False
    label = host.rsplit(".", 1)[-1].lower()
    if label in _CODE_EXT:
        return False
    return label in _TLD


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
            if not _maskable(real):
                return real
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
        """Return a masked copy of an OpenAI-style messages list.

        Only natural-language content (user/assistant) and the arguments of the
        domain-blocking tools are masked. System prompts, tool *results* (file
        contents, command output, search hits) and the arguments of file/code
        tools are passed through verbatim, so the model reads the real codebase
        and never sees corrupted ``ALVO_n`` paths."""
        out: list[dict[str, Any]] = []
        for m in messages:
            role = m.get("role")
            if role in ("system", "tool"):
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
                    if fn.get("name") in _DOMAIN_TOOLS and isinstance(fn.get("arguments"), str):
                        fn["arguments"] = self.mask(fn["arguments"])
                    tc2["function"] = fn
                    new_tcs.append(tc2)
                mm["tool_calls"] = new_tcs
            out.append(mm)
        return out


class NullMasker(Masker):
    """Pass-through masker for when provider content moderation is not in play
    (masking disabled in config). Keeps the same interface as Masker."""

    @property
    def active(self) -> bool:
        return False

    def mask(self, text: str | None) -> str | None:
        return text

    def unmask(self, text: str | None) -> str | None:
        return text

    def unmask_obj(self, obj: Any) -> Any:
        return obj

    def mask_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return messages
