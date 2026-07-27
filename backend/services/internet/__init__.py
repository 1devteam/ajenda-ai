"""Governed internet access helpers for Ajenda runtime tools.

Modes:
- public_search / page_read / http_request — always-on spine
- browser_session / open_write — registered prototypes (env flag gated)

All privileged I/O should go through NetworkEgressAuthority where possible.
"""

from backend.services.internet.browser_session import run_browser_session
from backend.services.internet.contracts import PageSnapshot, SearchBundle, SearchHit
from backend.services.internet.modes import (
    PROTOTYPE_INTERNET_MODES,
    RESERVED_INTERNET_MODES,
    SHIPPED_INTERNET_MODES,
    InternetAccessMode,
    is_prototype_mode,
    is_reserved_mode,
    is_shipped_mode,
)
from backend.services.internet.open_write import execute_open_write, open_write_enabled
from backend.services.internet.page_read import fetch_public_page, normalize_page_url
from backend.services.internet.search import public_search, search_bundle_as_legacy_dict

__all__ = [
    "PROTOTYPE_INTERNET_MODES",
    "RESERVED_INTERNET_MODES",
    "SHIPPED_INTERNET_MODES",
    "InternetAccessMode",
    "PageSnapshot",
    "SearchBundle",
    "SearchHit",
    "execute_open_write",
    "fetch_public_page",
    "is_prototype_mode",
    "is_reserved_mode",
    "is_shipped_mode",
    "normalize_page_url",
    "open_write_enabled",
    "public_search",
    "run_browser_session",
    "search_bundle_as_legacy_dict",
]
