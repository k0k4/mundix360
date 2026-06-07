"""Security boundary helpers for the AI assistant.

- redact(): mask secrets in any text before it reaches the LLM, the UI or storage.
- is_secret_path(): deny reading secret files (.env, secrets/, keys).
- is_protected_write(): deny writing into the source tree via shell (code edits must
  go through the password-gated code-change flow instead).
- constant-time password compare for the code-edit gate.
"""
from __future__ import annotations

import hmac
import os
import re
from pathlib import Path

from ...config import settings

# Patterns of secret-like content to mask anywhere it appears.
_SECRET_PATTERNS = [
    re.compile(r"(DASHSCOPE_API_KEY\s*=\s*)\S+", re.I),
    re.compile(r"(AI_MASTER_PASSWORD\s*=\s*)\S+", re.I),
    re.compile(r"(MUNDIX_[A-Z0-9_]*(?:KEY|PASSWORD|TOKEN|SECRET)\s*=\s*)\S+", re.I),
    re.compile(r"\b(sk-[A-Za-z0-9]{12,})\b"),
    re.compile(r"(-----BEGIN [A-Z ]*PRIVATE KEY-----)[\s\S]+?(-----END [A-Z ]*PRIVATE KEY-----)"),
    re.compile(r"((?:password|passwd|secret|token|api[_-]?key)\s*[:=]\s*)\S+", re.I),
]

_REDACTED = "***REDACTED***"

# Files/dirs whose contents must never be exposed (even via shell).
_SECRET_PATH_TOKENS = (
    "/.env",
    "/secrets/",
    "/secrets",
    "/.git/",
    "id_rsa",
    "id_ed25519",
    ".pem",
    ".key",
)

# Bare filenames that carry credentials regardless of location.
_SECRET_FILENAMES = {
    "credentials",
    "credentials.json",
    "secrets.yaml",
    "secrets.yml",
    "secrets.json",
    ".netrc",
    ".pgpass",
    ".htpasswd",
}

# Live, runtime-known secret values to scrub verbatim (defence in depth).
def _live_secrets() -> list[str]:
    vals = [settings.dashscope_api_key, settings.ai_master_password]
    try:
        from . import config_store

        vals = config_store.live_secrets() or vals
    except Exception:
        pass
    return [v for v in vals if v and len(v) >= 6]


def redact(text: str | None) -> str:
    if not text:
        return text or ""
    out = text
    for pat in _SECRET_PATTERNS:
        if pat.groups >= 2:
            out = pat.sub(lambda m: m.group(1) + _REDACTED + m.group(2), out)
        else:
            out = pat.sub(lambda m: (m.group(1) if m.groups else "") + _REDACTED, out)
    for secret in _live_secrets():
        out = out.replace(secret, _REDACTED)
    return out


def _norm(path: str) -> str:
    """Absolute, symlink-resolved path. Relative paths anchor to the editable
    root (the project), NOT the process working directory — so both the security
    checks and the code-gate writes are independent of where the service runs."""
    try:
        p = str(path)
        if not os.path.isabs(p):
            p = os.path.join(settings.ai_editable_root, p)
        return os.path.realpath(os.path.abspath(p))
    except Exception:
        return os.path.abspath(str(path))


def resolve_in_root(path: str) -> str:
    """Public resolver: turn an AI-supplied (possibly relative) path into the
    real absolute path under the editable root."""
    return _norm(path)


def is_secret_path(path: str) -> bool:
    p = _norm(path)
    low = p.lower()
    if any(tok in low for tok in _SECRET_PATH_TOKENS):
        return True
    # any *.env file (e.g. configs/openrouter.env), not just the root .env
    if low.endswith(".env") or ".env." in os.path.basename(low):
        return True
    # credential-bearing config files
    if os.path.basename(low) in _SECRET_FILENAMES:
        return True
    # the AI memory db itself
    if p == _norm(settings.ai_db_path):
        return True
    return False


def is_protected_write(path: str) -> bool:
    """True if writing this path would modify the source tree (must use code gate)."""
    p = _norm(path)
    root = _norm(settings.ai_editable_root)
    if not (p == root or p.startswith(root + os.sep)):
        return False
    # data/ and logs/ under the root are runtime artifacts, not source.
    rel = os.path.relpath(p, root)
    if rel.split(os.sep)[0] in {"data", "logs", "bin"}:
        return False
    return True


# Shell tokens that would read or write protected assets, blocked pre-execution.
_SHELL_DENY = re.compile(
    r"(\.env\b|/secrets\b|id_rsa|id_ed25519|\.pem\b|\.key\b|"
    r"\bMUNDIX_AI_MASTER_PASSWORD\b|\bDASHSCOPE_API_KEY\b|"
    r"/proc/\d+/environ|/proc/self/environ|\bprintenv\b|(?:^|[;&|]\s*)env\b|"
    r"\.netrc\b|\.pgpass\b)",
    re.I,
)


def sanitized_env() -> dict[str, str]:
    """Process environment with secret-bearing variables stripped, so a shell
    command cannot exfiltrate them via printenv / /proc/self/environ / etc."""
    secrets = set(_live_secrets())
    out: dict[str, str] = {}
    for k, v in os.environ.items():
        ku = k.upper()
        if any(tok in ku for tok in ("KEY", "PASSWORD", "PASSWD", "SECRET", "TOKEN")):
            continue
        if v in secrets:
            continue
        out[k] = v
    return out


def shell_precheck(cmd: str) -> str | None:
    """Return a denial reason if the shell command touches protected assets."""
    if _SHELL_DENY.search(cmd):
        return (
            "Comando bloqueado: acessa segredos protegidos (.env/secrets/chaves/env). "
            "Use as ferramentas tipadas; edição de código exige o portão de senha."
        )
    # crude write-redirection into the source tree
    m = re.search(r"(?:>>?|tee\s+|cp\s+\S+\s+|mv\s+\S+\s+)(/\S+)", cmd)
    if m and is_protected_write(m.group(1)):
        return (
            "Comando bloqueado: escreveria na árvore de código-fonte. "
            "Edição de código deve passar por propose_code_change (senha master)."
        )
    return None


def password_ok(candidate: str) -> bool:
    try:
        from . import config_store

        return config_store.verify_master_password(candidate)
    except Exception:
        pass
    expected = settings.ai_master_password
    if not expected:
        return False
    return hmac.compare_digest(str(candidate), str(expected))


def in_editable_root(path: str) -> bool:
    p = _norm(path)
    root = _norm(settings.ai_editable_root)
    return p == root or p.startswith(root + os.sep)
