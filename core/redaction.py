"""
core/redaction.py — deterministic sensitive-data redaction for LLM prompts.

Purpose
-------
Before sending user prompts / tool context to Ollama (or any LLM endpoint),
we redact obvious sensitive data such as:
- emails
- phone numbers
- API keys / secret tokens (heuristic patterns)

This module is intentionally conservative and deterministic:
- It uses regex replacements only (no ML).
- It never HTML-escapes.
- It preserves readability by keeping lightweight “[REDACTED: TYPE]” markers.

Usage
-----
Use `redact_text(text, enabled, strictness, blocklist_patterns)`.

Strictness
----------
- light  : emails, phone numbers, and common API key formats
- normal : adds longer generic token redaction heuristics
- strict : adds aggressive redaction for additional secret-like patterns

Blocklist
----------
blocklist_patterns: list[str]
Each pattern is treated as a regex; if it compiles it is applied.
If it doesn't compile, we fall back to plain substring replacement.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Union


_EMAIL_RE = re.compile(r"\b[\w\.-]+@[\w\.-]+\.\w+\b", re.IGNORECASE)

# Flexible phone patterns: +CC, separators, parentheses, etc.
_PHONE_RE = re.compile(
    r"""
    \b
    (?:\+?\d{1,3}[\s-]?)?          # optional country code
    (?:\(?\d{2,4}\)?[\s-]?)?      # optional area code
    \d{3,4}[\s-]?\d{3,4}          # main number parts
    \b
    """,
    re.VERBOSE,
)

# Common secret/token patterns
_OPENAI_SK_RE = re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")
_GENERIC_KEYPAIR_RE = re.compile(
    r"""
    \b
    (?i:(api[_-]?key|secret|token|access[_-]?token|bearer))
    \b\s*[:=]\s*
    ["']?
    [A-Za-z0-9_\-]{8,}
    ["']?
    \b
    """,
    re.VERBOSE,
)

# JWT-ish (three base64url-ish segments)
_JWT_RE = re.compile(r"\b[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")

# Long hex blobs (often keys, hashes, etc.) — conservative: >= 32 hex chars
_HEX_BLOB_RE = re.compile(r"\b[a-fA-F0-9]{32,}\b")


def _safe_apply_blocklist(text: str, blocklist_patterns: Iterable[str]) -> str:
    out = text
    for pat in blocklist_patterns:
        if not pat:
            continue
        try:
            rx = re.compile(pat)
        except re.error:
            # Fallback to plain substring replacement (simple + deterministic)
            out = out.replace(pat, "[REDACTED: BLOCKLIST]")
            continue
        out = rx.sub("[REDACTED: BLOCKLIST]", out)
    return out


def redact_text(
    text: str,
    *,
    enabled: bool = True,
    strictness: str = "normal",
    blocklist_patterns: Optional[Union[List[str], str]] = None,
) -> str:
    """
    Redact sensitive data in `text`.

    If enabled=False, returns text unchanged.
    """
    if not enabled or text is None:
        return text

    s = (strictness or "normal").strip().lower()
    if s not in ("light", "normal", "strict"):
        s = "normal"

    out = str(text)

    # Always apply these (light baseline)
    out = _EMAIL_RE.sub("[REDACTED: EMAIL]", out)
    out = _PHONE_RE.sub("[REDACTED: PHONE]", out)
    out = _OPENAI_SK_RE.sub("[REDACTED: API_KEY]", out)
    out = _GENERIC_KEYPAIR_RE.sub("[REDACTED: SECRET]", out)
    out = _JWT_RE.sub("[REDACTED: JWT]", out)

    # Escalate with strictness
    if s in ("normal", "strict"):
        out = _HEX_BLOB_RE.sub("[REDACTED: HEX_BLOB]", out)

    if s == "strict":
        # Additional secret-like heuristic:
        # redact long digit runs that could be OTPs/IDs if they appear alone-ish.
        out = re.sub(r"\b\d{10,}\b", "[REDACTED: LONG_NUMBER]", out)

    if blocklist_patterns:
        # Accept either:
        # - list[str]
        # - a single string containing patterns (split on ; , or newlines)
        patterns: List[str]
        if isinstance(blocklist_patterns, str):
            raw = blocklist_patterns.replace("\n", ";").replace(",", ";")
            patterns = [p.strip() for p in raw.split(";") if p.strip()]
        else:
            patterns = list(blocklist_patterns)

        out = _safe_apply_blocklist(out, patterns)

    return out
