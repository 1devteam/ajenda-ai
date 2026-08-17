"""Conservative contact extraction from fetched page text.

Does not invent mailboxes. Prefers mailto/tel. Drops noreply/privacy/placeholder domains.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlparse

_MAILTO_RE = re.compile(r"mailto:([^?\s\"'<>]+)", re.IGNORECASE)
_TEL_RE = re.compile(r"tel:([^?\s\"'<>]+)", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?<!\w)(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\w)")

_DROP_LOCAL = frozenset(
    {
        "noreply",
        "no-reply",
        "donotreply",
        "privacy",
        "webmaster",
        "postmaster",
        "mailer-daemon",
    }
)
_DROP_DOMAIN_PARTS = (
    "wordpress",
    "wixpress",
    "sentry.io",
    "example.com",
    "example.org",
    "invalid",
    "localhost",
    "schema.org",
    "w3.org",
)


def _normalize_email(raw: str) -> str | None:
    email = unquote(raw).strip().strip(".,;:<>()[]").lower()
    if "@" not in email or email.count("@") != 1:
        return None
    local, _, domain = email.partition("@")
    if not local or not domain or "." not in domain:
        return None
    if local in _DROP_LOCAL or local.startswith("noreply"):
        return None
    if any(part in domain for part in _DROP_DOMAIN_PARTS):
        return None
    return email


def _normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", unquote(raw))
    if digits.startswith("1") and len(digits) == 11:
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return f"({digits[0:3]}) {digits[3:6]}-{digits[6:10]}"


def extract_observed_contacts(*, text: str, source_url: str) -> list[dict[str, Any]]:
    """Return unique real-looking emails/phones found in page text."""

    found: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(*, kind: str, value: str, via: str) -> None:
        key = f"{kind}:{value}"
        if key in seen:
            return
        seen.add(key)
        found.append(
            {
                "kind": kind,
                "value": value,
                "source_url": source_url,
                "real": True,
                "via": via,
            }
        )

    for match in _MAILTO_RE.finditer(text):
        email = _normalize_email(match.group(1))
        if email:
            add(kind="email", value=email, via="mailto")
    for match in _TEL_RE.finditer(text):
        phone = _normalize_phone(match.group(1))
        if phone:
            add(kind="phone", value=phone, via="tel")
    for match in _EMAIL_RE.finditer(text):
        email = _normalize_email(match.group(0))
        if email:
            add(kind="email", value=email, via="text")
    for match in _PHONE_RE.finditer(text):
        phone = _normalize_phone(match.group(0))
        if phone:
            add(kind="phone", value=phone, via="text")
    return found


def prospect_source_url(prospect: dict[str, Any]) -> str | None:
    for key in ("url", "website", "source_url"):
        raw = prospect.get(key)
        if isinstance(raw, str) and raw.strip().startswith("http"):
            return raw.strip()
    domain = prospect.get("domain")
    if isinstance(domain, str) and domain.strip():
        host = domain.strip().removeprefix("https://").removeprefix("http://")
        if host and "." in host:
            return f"https://{host.lstrip('/')}"
    return None


def page_host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return host
