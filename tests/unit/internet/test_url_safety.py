from __future__ import annotations

import pytest

from backend.services.internet.url_safety import reject_credentialed_url


def test_rejects_userinfo() -> None:
    with pytest.raises(ValueError, match="userinfo"):
        reject_credentialed_url("https://user:secret@example.com/x", action_name="web.open_write")


def test_rejects_api_key_query() -> None:
    with pytest.raises(ValueError, match="credential"):
        reject_credentialed_url("https://example.com/x?api_key=abc", action_name="web.open_write")


def test_accepts_clean_https() -> None:
    assert reject_credentialed_url("https://example.com/path", action_name="web.page_read") == (
        "https://example.com/path"
    )
