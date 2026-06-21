"""Tenant slug allocation utilities."""

from __future__ import annotations

import re
import secrets

from backend.repositories.tenant_repository import TenantRepository

RESERVED_SLUGS = frozenset(
    {
        "admin",
        "api",
        "www",
        "billing",
        "onboarding",
        "signup",
        "health",
        "metrics",
        "system",
        "v1",
        "auth",
        "webhook",
    }
)

_SLUG_PATTERN = re.compile(r"^[a-z0-9-]{1,100}$")
_SLUGIFY_PATTERN = re.compile(r"[^a-z0-9]+")


class InvalidSlugError(ValueError):
    """Raised when a client-provided slug fails validation."""


def slugify_org_name(name: str) -> str:
    """Convert an organization name into a URL-safe slug candidate."""
    normalized = name.strip().lower()
    slug = _SLUGIFY_PATTERN.sub("-", normalized).strip("-")
    return slug[:60] if slug else "org"


def validate_client_slug(slug: str) -> str:
    """Validate and return a client-provided slug."""
    candidate = slug.strip().lower()
    if not _SLUG_PATTERN.fullmatch(candidate):
        raise InvalidSlugError("slug must match ^[a-z0-9-]{1,100}$")
    if candidate in RESERVED_SLUGS:
        raise InvalidSlugError(f"slug {candidate!r} is reserved")
    return candidate


def allocate_slug(
    repo: TenantRepository,
    *,
    org_name: str,
    client_slug: str | None = None,
    max_attempts: int = 12,
) -> str:
    """Return a slug candidate for tenant provisioning.

    When ``client_slug`` is provided it is validated and returned as-is.
    Auto allocation generates a base slug from ``org_name`` plus random
    suffix candidates. The database unique constraint remains authoritative.
    """
    if client_slug is not None:
        return validate_client_slug(client_slug)

    base = slugify_org_name(org_name)
    if base in RESERVED_SLUGS:
        base = f"{base}-org"

    candidates = [base]
    candidates.extend(f"{base}-{secrets.token_hex(3)}" for _ in range(max_attempts - 1))

    for candidate in candidates:
        if candidate in RESERVED_SLUGS:
            continue
        existing = repo.get_by_slug(candidate)
        if existing is None:
            return candidate

    return f"{base}-{secrets.token_hex(4)}"
