"""Internet access modes — progressive capability surface.

Shipped modes are registered runtime actions (may still be flag-gated).
Prototype modes ship as fail-closed actions until env flags enable them.
"""

from __future__ import annotations

from enum import StrEnum


class InternetAccessMode(StrEnum):
    """Canonical internet access modes for product + runtime evidence."""

    PUBLIC_SEARCH = "public_search"
    PAGE_READ = "page_read"
    HTTP_REQUEST = "http_request"
    BROWSER_SESSION = "browser_session"
    OPEN_WRITE = "open_write"


# Always-on modes (subject only to runtime promotion / side-effect rules).
SHIPPED_INTERNET_MODES: frozenset[InternetAccessMode] = frozenset(
    {
        InternetAccessMode.PUBLIC_SEARCH,
        InternetAccessMode.PAGE_READ,
        InternetAccessMode.HTTP_REQUEST,
    }
)

# Registered actions exist; require env enablement before live side effects.
PROTOTYPE_INTERNET_MODES: frozenset[InternetAccessMode] = frozenset(
    {
        InternetAccessMode.BROWSER_SESSION,
        InternetAccessMode.OPEN_WRITE,
    }
)

# Backward-compatible alias used by earlier phase docs/tests.
RESERVED_INTERNET_MODES = PROTOTYPE_INTERNET_MODES


def is_shipped_mode(mode: InternetAccessMode | str) -> bool:
    try:
        return InternetAccessMode(mode) in SHIPPED_INTERNET_MODES
    except ValueError:
        return False


def is_reserved_mode(mode: InternetAccessMode | str) -> bool:
    """True for prototype modes (flag-gated). Kept name for older callers."""

    try:
        return InternetAccessMode(mode) in PROTOTYPE_INTERNET_MODES
    except ValueError:
        return False


def is_prototype_mode(mode: InternetAccessMode | str) -> bool:
    return is_reserved_mode(mode)
