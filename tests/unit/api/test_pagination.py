"""Unit tests for cursor-based pagination primitives.

Verifies encode/decode roundtrip, error handling on malformed cursors,
and PaginatedResponse.build() correctness.
"""
from __future__ import annotations

import uuid

import pytest

from backend.api.pagination import (
    MAX_PAGE_SIZE,
    PaginatedResponse,
    decode_cursor,
    encode_cursor,
)


class TestCursorEncoding:
    def test_encode_decode_roundtrip(self) -> None:
        original = uuid.uuid4()
        cursor = encode_cursor(original)
        decoded = decode_cursor(cursor)
        assert decoded == original

    def test_cursor_is_url_safe(self) -> None:
        """Cursor must not contain characters that require URL encoding."""
        cursor = encode_cursor(uuid.uuid4())
        assert "+" not in cursor
        assert "/" not in cursor
        assert "=" not in cursor  # padding stripped

    def test_decode_malformed_cursor_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Invalid pagination cursor"):
            decode_cursor("this-is-not-a-valid-cursor!!!")

    def test_decode_empty_string_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            decode_cursor("")

    def test_encode_known_uuid(self) -> None:
        """Encoding must be deterministic for the same UUID."""
        uid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        assert encode_cursor(uid) == encode_cursor(uid)


class TestPaginatedResponse:
    def test_build_with_items_and_cursor(self) -> None:
        items = ["a", "b", "c"]
        cursor = encode_cursor(uuid.uuid4())
        response = PaginatedResponse[str].build(items=items, next_cursor=cursor, limit=10)
        assert response.items == items
        assert response.count == 3
        assert response.limit == 10
        assert response.next_cursor == cursor

    def test_build_last_page_has_no_cursor(self) -> None:
        items = ["x"]
        response = PaginatedResponse[str].build(items=items, next_cursor=None, limit=20)
        assert response.next_cursor is None

    def test_build_empty_page(self) -> None:
        response = PaginatedResponse[str].build(items=[], next_cursor=None, limit=20)
        assert response.items == []
        assert response.count == 0
        assert response.next_cursor is None

    def test_max_page_size_is_100(self) -> None:
        assert MAX_PAGE_SIZE == 100
