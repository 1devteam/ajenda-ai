from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, TypeVar, runtime_checkable

from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.db.tenant_session import activate_tenant_session
from backend.repositories.ephemeral_memory_chunk_repository import EphemeralMemoryChunkRepository
from backend.services.tools.schemas import ActionRuntimeContext

_T = TypeVar("_T")


@runtime_checkable
class MemoryChunkStore(Protocol):
    def upsert_chunk(
        self,
        *,
        tenant_id: str,
        content: str,
        mission_id: str | None = None,
        source: str = "runtime",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def keyword_search(
        self,
        *,
        tenant_id: str,
        query: str,
        mission_id: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]: ...

    def vector_search(
        self,
        *,
        tenant_id: str,
        query: str,
        mission_id: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]: ...


class DurableMemoryChunkStore:
    def __init__(self, repository: EphemeralMemoryChunkRepository, *, ttl_seconds: int) -> None:
        self._repo = repository
        self._ttl_seconds = ttl_seconds

    def upsert_chunk(
        self,
        *,
        tenant_id: str,
        content: str,
        mission_id: str | None = None,
        source: str = "runtime",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        expires_at = None
        if self._ttl_seconds > 0:
            expires_at = datetime.now(UTC) + timedelta(seconds=self._ttl_seconds)
        return self._repo.upsert_chunk(
            tenant_id=tenant_id,
            content=content,
            mission_id=mission_id,
            source=source,
            metadata=metadata,
            expires_at=expires_at,
        )

    def keyword_search(
        self,
        *,
        tenant_id: str,
        query: str,
        mission_id: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        return self._repo.keyword_search(
            tenant_id=tenant_id,
            query=query,
            mission_id=mission_id,
            limit=limit,
        )

    def vector_search(
        self,
        *,
        tenant_id: str,
        query: str,
        mission_id: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        settings = get_settings()
        if not settings.vector_search_enabled:
            return self.keyword_search(
                tenant_id=tenant_id,
                query=query,
                mission_id=mission_id,
                limit=limit,
            )
        return self._repo.vector_search(
            tenant_id=tenant_id,
            query=query,
            mission_id=mission_id,
            limit=limit,
        )


class SessionScopedMemoryChunkStore:
    def __init__(self, session_factory: Callable[[], Session], tenant_id: str, *, ttl_seconds: int) -> None:
        self._session_factory = session_factory
        self._tenant_id = tenant_id
        self._ttl_seconds = ttl_seconds

    def _with_store(self, operation: Callable[[DurableMemoryChunkStore], _T]) -> _T:
        session = self._session_factory()
        try:
            activate_tenant_session(session, self._tenant_id)
            result = operation(
                DurableMemoryChunkStore(
                    EphemeralMemoryChunkRepository(session),
                    ttl_seconds=self._ttl_seconds,
                )
            )
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def upsert_chunk(
        self,
        *,
        tenant_id: str,
        content: str,
        mission_id: str | None = None,
        source: str = "runtime",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._with_store(
            lambda store: store.upsert_chunk(
                tenant_id=tenant_id,
                content=content,
                mission_id=mission_id,
                source=source,
                metadata=metadata,
            )
        )

    def keyword_search(
        self,
        *,
        tenant_id: str,
        query: str,
        mission_id: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        return self._with_store(
            lambda store: store.keyword_search(
                tenant_id=tenant_id,
                query=query,
                mission_id=mission_id,
                limit=limit,
            )
        )

    def vector_search(
        self,
        *,
        tenant_id: str,
        query: str,
        mission_id: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        return self._with_store(
            lambda store: store.vector_search(
                tenant_id=tenant_id,
                query=query,
                mission_id=mission_id,
                limit=limit,
            )
        )


class InMemoryMemoryChunkStore:
    def __init__(self) -> None:
        self._chunks: list[dict[str, Any]] = []

    def upsert_chunk(
        self,
        *,
        tenant_id: str,
        content: str,
        mission_id: str | None = None,
        source: str = "runtime",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        chunk = {
            "id": f"mem-{len(self._chunks) + 1}",
            "tenant_id": tenant_id,
            "mission_id": mission_id,
            "content": content,
            "source": source,
            "metadata": dict(metadata or {}),
            "score": 0.5,
            "search_mode": "in_memory",
        }
        self._chunks.append(chunk)
        return chunk

    def keyword_search(
        self,
        *,
        tenant_id: str,
        query: str,
        mission_id: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        needle = query.lower()
        matches = [
            chunk
            for chunk in self._chunks
            if chunk["tenant_id"] == tenant_id
            and (mission_id is None or chunk.get("mission_id") in {None, mission_id})
            and needle in str(chunk.get("content", "")).lower()
        ]
        return matches[:limit]

    def vector_search(
        self,
        *,
        tenant_id: str,
        query: str,
        mission_id: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        return self.keyword_search(
            tenant_id=tenant_id,
            query=query,
            mission_id=mission_id,
            limit=limit,
        )


def resolve_memory_chunk_store(context: ActionRuntimeContext) -> MemoryChunkStore:
    settings = get_settings()
    if not settings.vector_db_enabled:
        return InMemoryMemoryChunkStore()
    vector_session_factory = getattr(context, "vector_session_factory", None)
    if vector_session_factory is None:
        return InMemoryMemoryChunkStore()
    return SessionScopedMemoryChunkStore(
        vector_session_factory,
        context.tenant_id,
        ttl_seconds=settings.ephemeral_memory_ttl_seconds,
    )