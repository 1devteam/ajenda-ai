from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.services.document_artifacts import list_review_queue, persist_artifact, update_review_status


@patch("backend.services.document_artifacts.TenantInternalRecordRepository")
def test_persist_artifact_writes_document_record(mock_repo_cls: MagicMock) -> None:
    repo = MagicMock()
    mock_repo_cls.return_value = repo
    repo.write_record.return_value = {
        "id": "pitch_email-abc123",
        "artifact_type": "pitch_email",
        "review_status": "pending",
        "content": {"subject": "Hi", "body": "Hello"},
    }

    saved = persist_artifact(
        MagicMock(),
        tenant_id="tenant-1",
        artifact_type="pitch_email",
        content={"subject": "Hi", "body": "Hello"},
    )

    assert saved["artifact_id"].startswith("pitch_email-")
    repo.write_record.assert_called_once()
    kwargs = repo.write_record.call_args.kwargs
    assert kwargs["record_type"] == "document"
    assert kwargs["tenant_id"] == "tenant-1"


@patch("backend.services.document_artifacts.TenantInternalRecordRepository")
def test_list_review_queue_filters_pending(mock_repo_cls: MagicMock) -> None:
    repo = MagicMock()
    mock_repo_cls.return_value = repo
    repo.search_records.return_value = [
        {"id": "follow_up-1", "artifact_type": "follow_up", "review_status": "pending", "content": {"draft": "Hi"}}
    ]

    rows = list_review_queue(MagicMock(), tenant_id="tenant-1", status="pending", limit=5)

    assert len(rows) == 1
    assert rows[0]["artifact_id"] == "follow_up-1"
    repo.search_records.assert_called_once_with(
        tenant_id="tenant-1",
        record_type="document",
        query="",
        filters={"review_status": "pending"},
        limit=5,
    )


@patch("backend.services.document_artifacts.read_artifact")
@patch("backend.services.document_artifacts.TenantInternalRecordRepository")
def test_update_review_status_marks_approved(mock_repo_cls: MagicMock, mock_read: MagicMock) -> None:
    mock_read.return_value = {
        "id": "pitch_email-abc123",
        "artifact_type": "pitch_email",
        "review_status": "pending",
        "content": {"subject": "Hi", "body": "Hello"},
        "metadata": {},
    }
    repo = MagicMock()
    mock_repo_cls.return_value = repo
    repo.write_record.return_value = {
        "id": "pitch_email-abc123",
        "artifact_type": "pitch_email",
        "review_status": "approved",
        "content": {"subject": "Hi", "body": "Hello"},
        "metadata": {"review_actor": "operator"},
    }

    saved = update_review_status(
        MagicMock(),
        tenant_id="tenant-1",
        artifact_id="pitch_email-abc123",
        review_status="approved",
        actor="operator",
        note="Looks good",
    )

    assert saved["review_status"] == "approved"
    assert saved["artifact_id"] == "pitch_email-abc123"
