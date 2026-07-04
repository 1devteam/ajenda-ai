from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.services.clerical_library import DEMO_CAPABILITY_RESUME_ID, DEMO_ROI_BRIEF_ID, seed_clerical_library


@patch("backend.services.clerical_library.persist_artifact")
def test_seed_clerical_library_writes_two_documents(mock_persist: MagicMock) -> None:
    mock_persist.side_effect = lambda *args, **kwargs: {"artifact_id": kwargs.get("artifact_id")}
    saved = seed_clerical_library(session=MagicMock(), tenant_id="tenant-1")
    assert saved == [DEMO_CAPABILITY_RESUME_ID, DEMO_ROI_BRIEF_ID]
    assert mock_persist.call_count == 2
