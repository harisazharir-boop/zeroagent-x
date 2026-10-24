"""Best-effort secret redaction and data minimization before persistence."""

from __future__ import annotations

import re
from typing import Any

SENSITIVE_FIELD_PARTS = frozenset(
    {"api_key", "apikey", "password", "secret", "token", "authorization", "credential"}
)
PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[a-z0-9._~+/=-]+"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)(api[_-]?key|password|token)\s*[=:]\s*[^\s,;]+"),
)
REDACTED = "[REDACTED]"


def redact_text(value: str, *, limit: int = 256) -> str:
    """Redact common secret forms and bound persisted free text."""
    sanitized = value
    for pattern in PATTERNS:
        sanitized = pattern.sub(REDACTED, sanitized)
    return sanitized[:limit]


def redact_value(value: Any, *, field_name: str = "") -> Any:
    """Recursively redact known sensitive fields without retaining arbitrary objects."""
    normalized_name = field_name.casefold().replace("-", "_")
    if any(part in normalized_name for part in SENSITIVE_FIELD_PARTS):
        return REDACTED
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, bool | int | float) or value is None:
        return value
    if isinstance(value, list | tuple):
        return [redact_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): redact_value(item, field_name=str(key))
            for key, item in value.items()
        }
    raise ValueError(
        f"Unsupported value type for safe recording: {type(value).__name__}"
    )
