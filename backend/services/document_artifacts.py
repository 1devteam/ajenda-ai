from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy.orm import Session

from backend.repositories.tenant_internal_record_repository import TenantInternalRecordRepository

DOCUMENT_RECORD_TYPE = "document"
SUPPORTED_ARTIFACT_TYPES = frozenset({"pitch_email", "capability_resume", "roi_brief", "follow_up"})
ReviewStatus = Literal["pending", "approved", "rejected", "sent"]


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def new_artifact_id(*, artifact_type: str) -> str:
    return f"{artifact_type}-{uuid.uuid4().hex[:12]}"


def persist_artifact(
    session: Session,
    *,
    tenant_id: str,
    artifact_type: str,
    content: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    artifact_id: str | None = None,
    review_status: ReviewStatus = "pending",
    mission_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    normalized_type = artifact_type.strip().lower()
    if normalized_type not in SUPPORTED_ARTIFACT_TYPES:
        raise ValueError(f"unsupported artifact_type: {artifact_type}")

    final_id = artifact_id or new_artifact_id(artifact_type=normalized_type)
    record = {
        "artifact_type": normalized_type,
        "review_status": review_status,
        "content": content,
        "metadata": metadata or {},
        "mission_id": mission_id,
        "task_id": task_id,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    saved = TenantInternalRecordRepository(session).write_record(
        tenant_id=tenant_id,
        record_type=DOCUMENT_RECORD_TYPE,
        record_id=final_id,
        data=record,
    )
    saved["artifact_id"] = final_id
    return saved


def read_artifact(session: Session, *, tenant_id: str, artifact_id: str) -> dict[str, Any] | None:
    record = TenantInternalRecordRepository(session).read_record(
        tenant_id=tenant_id,
        record_type=DOCUMENT_RECORD_TYPE,
        record_id=artifact_id,
    )
    if record is None:
        return None
    record["artifact_id"] = record.get("id", artifact_id)
    return record


def list_review_queue(
    session: Session,
    *,
    tenant_id: str,
    status: ReviewStatus = "pending",
    limit: int = 20,
) -> list[dict[str, Any]]:
    repo = TenantInternalRecordRepository(session)
    rows = repo.search_records(
        tenant_id=tenant_id,
        record_type=DOCUMENT_RECORD_TYPE,
        query="",
        filters={"review_status": status},
        limit=limit,
    )
    for row in rows:
        row["artifact_id"] = row.get("id")
    return rows


def update_review_status(
    session: Session,
    *,
    tenant_id: str,
    artifact_id: str,
    review_status: ReviewStatus,
    actor: str,
    note: str | None = None,
) -> dict[str, Any]:
    existing = read_artifact(session, tenant_id=tenant_id, artifact_id=artifact_id)
    if existing is None:
        raise ValueError(f"artifact not found: {artifact_id}")

    updated = dict(existing)
    updated["review_status"] = review_status
    updated["updated_at"] = _now_iso()
    review_meta = dict(updated.get("metadata") or {})
    review_meta["review_actor"] = actor
    if note:
        review_meta["review_note"] = note
    updated["metadata"] = review_meta

    saved = TenantInternalRecordRepository(session).write_record(
        tenant_id=tenant_id,
        record_type=DOCUMENT_RECORD_TYPE,
        record_id=artifact_id,
        data=updated,
    )
    saved["artifact_id"] = artifact_id
    return saved
