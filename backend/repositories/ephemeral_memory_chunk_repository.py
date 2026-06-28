from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.domain.ephemeral_memory_chunk import EphemeralMemoryChunk
from backend.services.data_plane.embeddings import cosine_similarity, deterministic_embedding


class EphemeralMemoryChunkRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_chunk(
        self,
        *,
        tenant_id: str,
        content: str,
        mission_id: str | None = None,
        source: str = "runtime",
        metadata: dict[str, Any] | None = None,
        expires_at: datetime | None = None,
        chunk_id: str | None = None,
    ) -> dict[str, Any]:
        normalized = content.strip()
        if not normalized:
            raise ValueError("content must be non-empty")
        final_id = chunk_id or f"emc-{uuid.uuid4()}"
        search_text = normalized.lower()
        embedding = deterministic_embedding(search_text)
        now = datetime.now(UTC)

        stmt = select(EphemeralMemoryChunk).where(
            EphemeralMemoryChunk.tenant_id == tenant_id,
            EphemeralMemoryChunk.id == final_id,
        )
        existing = self._session.scalars(stmt).first()
        if existing is None:
            row = EphemeralMemoryChunk(
                id=final_id,
                tenant_id=tenant_id,
                mission_id=mission_id,
                content=normalized,
                search_text=search_text,
                embedding_json=embedding,
                source=source,
                metadata_json=dict(metadata or {}),
                expires_at=expires_at,
                created_at=now,
                updated_at=now,
            )
            self._session.add(row)
        else:
            existing.mission_id = mission_id
            existing.content = normalized
            existing.search_text = search_text
            existing.embedding_json = embedding
            existing.source = source
            existing.metadata_json = dict(metadata or {})
            existing.expires_at = expires_at
            existing.updated_at = now
            row = existing
        self._session.flush()
        return self._to_dict(row)

    def keyword_search(
        self,
        *,
        tenant_id: str,
        query: str,
        mission_id: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if limit < 1 or limit > 50:
            raise ValueError("limit must be between 1 and 50")
        stmt = select(EphemeralMemoryChunk).where(EphemeralMemoryChunk.tenant_id == tenant_id)
        stmt = self._apply_active_filters(stmt, mission_id=mission_id)
        pattern = f"%{query.lower().strip()}%"
        if query.strip():
            stmt = stmt.where(
                or_(
                    EphemeralMemoryChunk.search_text.ilike(pattern),
                    EphemeralMemoryChunk.content.ilike(pattern),
                )
            )
        rows = list(self._session.scalars(stmt.order_by(EphemeralMemoryChunk.updated_at.desc()).limit(limit)).all())
        return [self._to_dict(row, score=1.0, search_mode="keyword") for row in rows]

    def vector_search(
        self,
        *,
        tenant_id: str,
        query: str,
        mission_id: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if limit < 1 or limit > 50:
            raise ValueError("limit must be between 1 and 50")
        query_embedding = deterministic_embedding(query.lower().strip())
        stmt = select(EphemeralMemoryChunk).where(EphemeralMemoryChunk.tenant_id == tenant_id)
        stmt = self._apply_active_filters(stmt, mission_id=mission_id)
        rows = list(self._session.scalars(stmt.limit(limit * 10)).all())
        scored: list[tuple[float, EphemeralMemoryChunk]] = []
        for row in rows:
            embedding = row.embedding_json if isinstance(row.embedding_json, list) else []
            score = cosine_similarity(query_embedding, [float(item) for item in embedding])
            scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            self._to_dict(row, score=score, search_mode="vector")
            for score, row in scored[:limit]
            if score > 0.0
        ]

    def _apply_active_filters(self, stmt, *, mission_id: str | None):
        now = datetime.now(UTC)
        stmt = stmt.where(or_(EphemeralMemoryChunk.expires_at.is_(None), EphemeralMemoryChunk.expires_at > now))
        if mission_id:
            stmt = stmt.where(
                or_(EphemeralMemoryChunk.mission_id.is_(None), EphemeralMemoryChunk.mission_id == mission_id)
            )
        return stmt

    @staticmethod
    def _to_dict(row: EphemeralMemoryChunk, *, score: float | None = None, search_mode: str | None = None) -> dict[str, Any]:
        payload = {
            "id": row.id,
            "tenant_id": row.tenant_id,
            "mission_id": row.mission_id,
            "content": row.content,
            "source": row.source,
            "metadata": dict(row.metadata_json or {}),
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
        }
        if score is not None:
            payload["score"] = round(score, 4)
        if search_mode is not None:
            payload["search_mode"] = search_mode
        return payload