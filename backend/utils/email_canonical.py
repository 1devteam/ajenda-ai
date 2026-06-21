"""Email canonicalization for signup identity authority.

Canonicalization is a security control: it prevents duplicate accounts via
provider-specific aliasing (Gmail dots/plus, Outlook plus-tags, case folding).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from email_validator import EmailNotValidError, validate_email

_GMAIL_DOMAINS = frozenset({"gmail.com", "googlemail.com"})
_OUTLOOK_DOMAINS = frozenset({"outlook.com", "hotmail.com", "live.com"})
_MAX_EMAIL_LENGTH = 320


@dataclass(frozen=True, slots=True)
class CanonicalEmail:
    raw: str
    canonical: str


class InvalidEmailError(ValueError):
    """Raised when an email address cannot be canonicalized."""


def canonicalize_email(raw: str) -> CanonicalEmail:
    """Normalize and canonicalize an email address for uniqueness checks."""
    if raw is None:
        raise InvalidEmailError("email is required")

    trimmed = unicodedata.normalize("NFKC", raw.strip())
    if not trimmed:
        raise InvalidEmailError("email is required")
    if len(trimmed) > _MAX_EMAIL_LENGTH:
        raise InvalidEmailError("email exceeds maximum length")

    try:
        validated = validate_email(trimmed, check_deliverability=False)
    except EmailNotValidError as exc:
        raise InvalidEmailError(str(exc)) from exc

    normalized = validated.normalized
    local, _, domain = normalized.partition("@")
    if not local or not domain:
        raise InvalidEmailError("invalid email address")

    domain_canonical = domain.lower()
    local_canonical = _canonicalize_local_part(local, domain_canonical)
    canonical = f"{local_canonical}@{domain_canonical}"

    if len(canonical) > _MAX_EMAIL_LENGTH:
        raise InvalidEmailError("email exceeds maximum length")

    return CanonicalEmail(raw=trimmed, canonical=canonical)


def _canonicalize_local_part(local: str, domain: str) -> str:
    lowered = local.lower()
    if domain in _GMAIL_DOMAINS:
        base, _, _suffix = lowered.partition("+")
        return base.replace(".", "")
    if domain in _OUTLOOK_DOMAINS:
        base, _, _suffix = lowered.partition("+")
        return base
    return lowered


def emails_equivalent(left: str, right: str) -> bool:
    """Return True when two raw emails canonicalize to the same identity."""
    return canonicalize_email(left).canonical == canonicalize_email(right).canonical
