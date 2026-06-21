"""Unit tests for slug allocation."""

from __future__ import annotations

import pytest

from backend.utils.slug import InvalidSlugError, allocate_slug, slugify_org_name, validate_client_slug


class _StubTenantRepo:
    def __init__(self, existing: set[str] | None = None) -> None:
        self._existing = existing or set()

    def get_by_slug(self, slug: str) -> object | None:
        return object() if slug in self._existing else None


def test_slugify_org_name_normalizes_spaces_and_case() -> None:
    assert slugify_org_name("  Acme Corp!!  ") == "acme-corp"


def test_validate_client_slug_rejects_reserved() -> None:
    with pytest.raises(InvalidSlugError):
        validate_client_slug("admin")


def test_allocate_slug_returns_client_slug_when_valid() -> None:
    slug = allocate_slug(_StubTenantRepo(), org_name="Acme", client_slug="acme-labs")
    assert slug == "acme-labs"


def test_allocate_slug_generates_unique_candidate() -> None:
    slug = allocate_slug(_StubTenantRepo(existing={"acme"}), org_name="Acme")
    assert slug != "acme"
    assert slug.startswith("acme")
