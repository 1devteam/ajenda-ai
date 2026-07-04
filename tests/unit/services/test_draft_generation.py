from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from backend.services.business_context_resolver import BusinessContext
from backend.services.draft_generation import generate_and_persist_draft
from backend.services.llm.contracts import LlmGenerateResult
from backend.services.tools.schemas import ActionRuntimeContext


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


@patch("backend.services.draft_generation.resolve_business_context")
@patch("backend.services.draft_generation.generate_text")
def test_generate_and_persist_draft_template_fallback(mock_generate: MagicMock, mock_biz: MagicMock) -> None:
    mock_biz.return_value = BusinessContext(
        business_name="Ajenda AI",
        company="Ajenda AI",
        domain="ajenda.ai",
        website="https://ajenda.ai",
        service_area=None,
        primary_contact_name=None,
        contact_email=None,
        contact_phone=None,
        target_customers=("SaaS teams",),
        products_services=("Governed runtime",),
        operator_notes=None,
        account_record_id=None,
        contact_record_id=None,
        source="business_profile",
    )
    mock_generate.return_value = LlmGenerateResult(
        text="template body",
        provider="template_fallback",
        model="template",
        used_llm=False,
    )

    output = generate_and_persist_draft(
        _context(),
        artifact_type="pitch_email",
        topic="pilot intro",
        tone="professional",
        recipient="ops@example.com",
    )

    assert output["to"] == "ops@example.com"
    assert output["generation_mode"] == "template"
    assert "Ajenda AI" in output["body"]
    assert output["artifact_id"] is None


@patch("backend.services.draft_generation.persist_artifact")
@patch("backend.services.draft_generation.resolve_business_context")
@patch("backend.services.draft_generation.generate_text")
def test_generate_and_persist_draft_persists_when_session_available(
    mock_generate: MagicMock,
    mock_biz: MagicMock,
    mock_persist: MagicMock,
) -> None:
    mock_biz.return_value = BusinessContext(
        business_name="Ajenda AI",
        company="Ajenda AI",
        domain=None,
        website=None,
        service_area=None,
        primary_contact_name=None,
        contact_email=None,
        contact_phone=None,
        target_customers=(),
        products_services=("Governed runtime",),
        operator_notes=None,
        account_record_id=None,
        contact_record_id=None,
        source="business_profile",
    )
    mock_generate.return_value = LlmGenerateResult(
        text='{"subject":"Pilot","body":"Hello there"}',
        provider="openai_compatible",
        model="gpt-4o-mini",
        used_llm=True,
    )
    mock_persist.return_value = {"artifact_id": "pitch_email-deadbeef", "review_status": "pending"}

    session = MagicMock()
    ctx = ActionRuntimeContext(
        tenant_id="tenant-1",
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker-1",
        lease_id="lease-1",
        runtime_credentials={},
        runtime_cache={},
        session_factory=lambda: session,
    )

    output = generate_and_persist_draft(
        ctx,
        artifact_type="pitch_email",
        topic="pilot intro",
        tone="professional",
        recipient="ops@example.com",
    )

    assert output["artifact_id"] == "pitch_email-deadbeef"
    assert output["generation_mode"] == "llm"
    session.commit.assert_called_once()
