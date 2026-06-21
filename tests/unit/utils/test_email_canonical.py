"""Unit tests for email canonicalization."""

from __future__ import annotations

import pytest

from backend.utils.email_canonical import InvalidEmailError, canonicalize_email, emails_equivalent


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Owner@Example.COM", "owner@example.com"),
        ("user+tag@gmail.com", "user@gmail.com"),
        ("u.ser@gmail.com", "user@gmail.com"),
        ("user@outlook.com", "user+tag@outlook.com"),
    ],
)
def test_canonical_equivalence_table(left: str, right: str) -> None:
    assert emails_equivalent(left, right)


def test_canonicalize_email_returns_raw_and_canonical() -> None:
    result = canonicalize_email("  Owner@Example.COM ")
    assert result.raw == "Owner@Example.COM"
    assert result.canonical == "owner@example.com"


@pytest.mark.parametrize("raw", ["", "   ", "not-an-email", "a" * 321])
def test_canonicalize_email_rejects_invalid(raw: str) -> None:
    with pytest.raises(InvalidEmailError):
        canonicalize_email(raw)
