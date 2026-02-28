"""
Input Sanitisation Utilities for Omnipath v2
Provides defence-in-depth against XSS, HTML injection, and SQL injection.

Note: SQLAlchemy ORM already uses parameterised queries (primary defence).
These utilities provide an additional layer for user-supplied strings that
are stored and later rendered in UI contexts.

Built with Pride for Obex Blackvault
"""

import re
import html
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# ── SQL injection pattern detection ───────────────────────────────────────────
# Used only for logging/alerting; the ORM is the primary SQL injection defence.
_SQL_INJECTION_PATTERNS: List[re.Pattern] = [
    re.compile(
        r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|EXEC|UNION|TRUNCATE)\b)",
        re.IGNORECASE,
    ),
    re.compile(r"(--|;|/\*|\*/|xp_|WAITFOR\s+DELAY)", re.IGNORECASE),
    re.compile(r"('|\"|`)(.*?)(--|;|OR\s+1=1|AND\s+1=1)", re.IGNORECASE),
]

# ── HTML/script tag patterns ───────────────────────────────────────────────────
_DANGEROUS_HTML_PATTERN = re.compile(
    r"<\s*(script|iframe|object|embed|form|input|link|meta|style|base|applet)"
    r"[^>]*>.*?</\s*\1\s*>|<\s*(script|iframe|object|embed|form|input|link|meta|style|base|applet)[^>]*/?>",  # noqa: E501
    re.IGNORECASE | re.DOTALL,
)

_EVENT_HANDLER_PATTERN = re.compile(
    r"\bon\w+\s*=",
    re.IGNORECASE,
)

_JAVASCRIPT_PROTOCOL_PATTERN = re.compile(
    r"javascript\s*:",
    re.IGNORECASE,
)


def sanitise_string(value: str, *, max_length: int = 10_000, allow_html: bool = False) -> str:
    """
    Sanitise a user-supplied string.

    Steps applied:
    1. Truncate to ``max_length`` characters.
    2. Strip null bytes.
    3. If ``allow_html`` is False, HTML-escape the string.
    4. Log a warning if SQL injection patterns are detected (ORM is the real defence).

    Args:
        value: The raw user input string.
        max_length: Maximum allowed length (default 10 000 characters).
        allow_html: If True, skip HTML escaping (use only when rendering trusted HTML).

    Returns:
        Sanitised string safe for storage and rendering.
    """
    if not isinstance(value, str):
        return value  # type: ignore[return-value]

    # 1. Truncate
    value = value[:max_length]

    # 2. Strip null bytes (can bypass filters in some databases)
    value = value.replace("\x00", "")

    # 3. HTML escape (prevents XSS when value is rendered in HTML context)
    if not allow_html:
        value = html.escape(value, quote=True)

    # 4. Detect and log SQL injection attempts (informational; ORM prevents actual injection)
    for pattern in _SQL_INJECTION_PATTERNS:
        if pattern.search(value):
            logger.warning(
                "Potential SQL injection pattern detected in input",
                extra={"pattern": pattern.pattern, "value_preview": value[:100]},
            )
            break

    return value


def sanitise_html(value: str, *, max_length: int = 50_000) -> str:
    """
    Strip dangerous HTML tags and event handlers from a string.

    Intended for fields that legitimately accept rich text (e.g., descriptions).
    Removes ``<script>``, ``<iframe>``, ``on*`` event handlers, and
    ``javascript:`` protocol references.

    Args:
        value: Raw HTML string from user input.
        max_length: Maximum allowed length.

    Returns:
        Sanitised HTML string with dangerous constructs removed.
    """
    if not isinstance(value, str):
        return value  # type: ignore[return-value]

    value = value[:max_length]
    value = value.replace("\x00", "")

    # Remove dangerous tags
    value = _DANGEROUS_HTML_PATTERN.sub("", value)

    # Remove event handlers (onclick=, onload=, etc.)
    value = _EVENT_HANDLER_PATTERN.sub("", value)

    # Remove javascript: protocol
    value = _JAVASCRIPT_PROTOCOL_PATTERN.sub("", value)

    return value


def sanitise_dict(
    data: Dict[str, Any],
    *,
    max_string_length: int = 10_000,
    allow_html: bool = False,
    depth: int = 0,
    max_depth: int = 10,
) -> Dict[str, Any]:
    """
    Recursively sanitise all string values in a dictionary.

    Args:
        data: Dictionary of user-supplied data (e.g., parsed JSON body).
        max_string_length: Maximum length for each string value.
        allow_html: If True, skip HTML escaping.
        depth: Current recursion depth (internal use).
        max_depth: Maximum recursion depth to prevent DoS via deeply nested objects.

    Returns:
        New dictionary with all string values sanitised.
    """
    if depth > max_depth:
        logger.warning("sanitise_dict: max recursion depth reached, truncating nested object")
        return {}

    result: Dict[str, Any] = {}
    for key, value in data.items():
        sanitised_key = sanitise_string(str(key), max_length=256) if isinstance(key, str) else key
        if isinstance(value, str):
            result[sanitised_key] = sanitise_string(
                value, max_length=max_string_length, allow_html=allow_html
            )
        elif isinstance(value, dict):
            result[sanitised_key] = sanitise_dict(
                value,
                max_string_length=max_string_length,
                allow_html=allow_html,
                depth=depth + 1,
                max_depth=max_depth,
            )
        elif isinstance(value, list):
            result[sanitised_key] = _sanitise_list(
                value,
                max_string_length=max_string_length,
                allow_html=allow_html,
                depth=depth + 1,
                max_depth=max_depth,
            )
        else:
            result[sanitised_key] = value

    return result


def _sanitise_list(
    data: List[Any],
    *,
    max_string_length: int,
    allow_html: bool,
    depth: int,
    max_depth: int,
) -> List[Any]:
    """Recursively sanitise a list of values."""
    if depth > max_depth:
        return []

    result: List[Any] = []
    for item in data:
        if isinstance(item, str):
            result.append(
                sanitise_string(item, max_length=max_string_length, allow_html=allow_html)
            )
        elif isinstance(item, dict):
            result.append(
                sanitise_dict(
                    item,
                    max_string_length=max_string_length,
                    allow_html=allow_html,
                    depth=depth + 1,
                    max_depth=max_depth,
                )
            )
        elif isinstance(item, list):
            result.append(
                _sanitise_list(
                    item,
                    max_string_length=max_string_length,
                    allow_html=allow_html,
                    depth=depth + 1,
                    max_depth=max_depth,
                )
            )
        else:
            result.append(item)

    return result
