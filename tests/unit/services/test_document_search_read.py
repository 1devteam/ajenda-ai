from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from backend.services.tools.document_actions import document_read_handler, document_search_handler
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation


def _context() -> ActionRuntimeContext:
    return ActionRuntimeContext(
        tenant_id="tenant-1",
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker-1",
        lease_id="lease-1",
        runtime_credentials={},
        runtime_cache={},
        session_factory=None,
    )


@patch("backend.services.tools.document_actions.resolve_record_store")
def test_document_search_returns_artifacts(mock_store: MagicMock) -> None:
    mock_store.return_value.search_records.return_value = [
        {
            "id": "roi_brief-demo",
            "artifact_type": "roi_brief",
            "review_status": "approved",
            "content": {"body": "ROI text"},
        }
    ]
    result = document_search_handler(
        ToolInvocation(action="document.search", input={"query": "ROI", "artifact_type": "roi_brief", "limit": 5}),
        _context(),
    )
    assert result.output["count"] == 1
    assert result.output["artifacts"][0]["artifact_id"] == "roi_brief-demo"


@patch("backend.services.tools.document_actions.resolve_record_store")
def test_document_read_returns_found_artifact(mock_store: MagicMock) -> None:
    mock_store.return_value.read_record.return_value = {
        "id": "capability_resume-ajenda-core",
        "artifact_type": "capability_resume",
        "content": {"body": "Capability text"},
    }
    result = document_read_handler(
        ToolInvocation(action="document.read", input={"artifact_id": "capability_resume-ajenda-core"}),
        _context(),
    )
    assert result.output["found"] is True
    assert result.output["artifact_id"] == "capability_resume-ajenda-core"
