"""Cursor-based pagination primitives for Ajenda AI API responses.

Design:
- Cursor is an opaque base64-encoded string containing the last-seen record's
  sort key (typically a UUID or (created_at, id) tuple). Clients treat it as
  opaque — they must not parse or construct cursors themselves.
- All list endpoints return PaginatedResponse[T] which carries the items, the
  next cursor (None when no more pages), and the total count of items in the
  current page.
- Page size is controlled by the caller via a `limit` query parameter, capped
  at MAX_PAGE_SIZE to prevent unbounded queries.
- The cursor is URL-safe base64 encoded to avoid encoding issues in query strings.

Usage in a route::

    from backend.api.pagination import PaginatedResponse, encode_cursor, decode_cursor, MAX_PAGE_SIZE

    @router.get("/tasks", response_model=PaginatedResponse[TaskResponse])
    def list_tasks(
        limit: int = Query(default=20, ge=1, le=MAX_PAGE_SIZE),
        cursor: str | None = Query(default=None),
        db: Session = Depends(get_db_session),
    ) -> PaginatedResponse[TaskResponse]:
        after_id = decode_cursor(cursor) if cursor else None
        tasks, next_cursor = task_repo.list_page(limit=limit, after_id=after_id)
        return PaginatedResponse.build(items=tasks, next_cursor=next_cursor, limit=limit)
"""

from __future__ import annotations

import base64
import uuid
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

MAX_PAGE_SIZE: int = 100
DEFAULT_PAGE_SIZE: int = 20


def encode_cursor(record_id: uuid.UUID) -> str:
    """Encode a UUID into an opaque, URL-safe cursor string."""
    raw = str(record_id).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> uuid.UUID:
    """Decode a cursor string back into a UUID.

    Raises ValueError if the cursor is malformed or does not contain a valid UUID.
    Callers should catch ValueError and return HTTP 400.
    """
    # Re-add stripped padding
    padding = 4 - len(cursor) % 4
    if padding != 4:
        cursor = cursor + "=" * padding
    try:
        raw = base64.urlsafe_b64decode(cursor).decode("utf-8")
        return uuid.UUID(raw)
    except Exception as exc:
        raise ValueError(f"Invalid pagination cursor: {cursor!r}") from exc


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response envelope.

    Attributes:
        items:       The current page of results.
        next_cursor: Opaque cursor to pass as `cursor` in the next request.
                     None when this is the last page.
        count:       Number of items in this page (not the total collection size).
        limit:       The page size that was applied.
    """

    items: list[T] = Field(description="Current page of results.")
    next_cursor: str | None = Field(
        default=None,
        description="Opaque cursor for the next page. Absent when no more pages exist.",
    )
    count: int = Field(description="Number of items in this page.")
    limit: int = Field(description="Page size applied to this response.")

    model_config = {"arbitrary_types_allowed": True}

    @classmethod
    def build(
        cls,
        *,
        items: list[T],
        next_cursor: str | None,
        limit: int,
    ) -> PaginatedResponse[T]:
        """Construct a PaginatedResponse from a list of items and an optional next cursor."""
        return cls(
            items=items,
            next_cursor=next_cursor,
            count=len(items),
            limit=limit,
        )
