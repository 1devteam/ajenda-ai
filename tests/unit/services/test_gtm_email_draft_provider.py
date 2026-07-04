from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from backend.services.tools.action_registry import ActionRegistry
from backend.services.tools.gtm_actions import register_gtm_actions
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


@patch("backend.services.tools.gtm_actions.generate_and_persist_draft")
def test_gtm_email_draft_returns_registered_provider(mock_draft: MagicMock) -> None:
    mock_draft.return_value = {
        "to": "ops@example.com",
        "subject": "Pilot",
        "body": "Hello",
        "generation_mode": "template",
        "artifact_id": "pitch_email-abc123",
    }
    registry = ActionRegistry()
    register_gtm_actions(registry)

    result = registry.invoke(
        ToolInvocation(
            action="gtm.email_draft",
            input={
                "recipient": "ops@example.com",
                "topic": "pilot",
                "tone": "professional",
            },
        ),
        _context(),
    )

    assert result.provider == "local_gtm"
    assert result.side_effect_class.value == "none"
    assert result.output["artifact_id"] == "pitch_email-abc123"
