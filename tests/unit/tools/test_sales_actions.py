from __future__ import annotations

import uuid

from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation


def _context() -> ActionRuntimeContext:
    return ActionRuntimeContext(
        tenant_id=str(uuid.uuid4()),
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker",
        lease_id=str(uuid.uuid4()),
    )


def test_sales_and_record_actions_return_evidence_shaped_output() -> None:
    registry = get_default_action_registry(rebuild=True)
    context = _context()

    result = registry.invoke(
        ToolInvocation(action="record.search", input={"record_type": "account", "query": "Acme"}), context
    )

    assert result.output["count"] == 1
    assert result.evidence[0].action_name == "record.search"
    assert result.evidence[0].tenant_id == context.tenant_id
    assert result.evidence[0].records_inspected == ["acct-1"]


def test_sales_qualify_score_and_recommendation_are_deterministic() -> None:
    registry = get_default_action_registry(rebuild=True)
    context = _context()
    lead = {"company": "Acme", "role": "VP", "intent": "expansion", "email": "avery@example.com"}

    score = registry.invoke(ToolInvocation(action="sales.score_lead", input={"lead": lead}), context)
    recommendation = registry.invoke(
        ToolInvocation(action="sales.recommend_next_action", input={"lead": lead}), context
    )

    assert score.output == {
        "lead_score": 100,
        "score_band": "high",
        "reasons": [
            "company/account context present",
            "buyer role context present",
            "intent signal present",
            "contactability present",
        ],
    }
    assert recommendation.output["recommendation"] == "draft_followup"


def test_aliases_map_to_sales_actions() -> None:
    registry = get_default_action_registry(rebuild=True)

    research = registry.invoke(
        ToolInvocation(action="crm.research", input={"lead": {"account_id": "acct-1"}}), _context()
    )
    draft = registry.invoke(
        ToolInvocation(action="gtm.message_draft", input={"recipient_name": "Avery", "topic": "pilot"}), _context()
    )

    assert research.action == "sales.research"
    assert "Drafted" in draft.summary


def test_record_write_is_observable_by_read() -> None:
    from backend.services.tools.local_records import reset_default_local_record_provider

    reset_default_local_record_provider()
    registry = get_default_action_registry(rebuild=True)
    context = _context()

    write_result = registry.invoke(
        ToolInvocation(
            action="record.write",
            input={
                "record_type": "contact",
                "record_id": "contact-new",
                "data": {"name": "New Contact", "role": "Buyer"},
            },
        ),
        context,
    )
    read_result = registry.invoke(
        ToolInvocation(
            action="record.read",
            input={"record_type": "contact", "record_id": "contact-new"},
        ),
        context,
    )

    assert write_result.records_changed == ["contact-new"]
    assert read_result.output["found"] is True
    assert read_result.output["record"]["name"] == "New Contact"


def test_sales_log_activity_preserves_record_write_payload_shape() -> None:
    from backend.services.tools.local_records import reset_default_local_record_provider

    reset_default_local_record_provider()
    registry = get_default_action_registry(rebuild=True)
    context = _context()

    result = registry.invoke(
        ToolInvocation(
            action="sales.log_activity",
            input={
                "record_type": "activity",
                "record_id": "activity-1",
                "data": {"note": "called buyer", "channel": "phone"},
            },
        ),
        context,
    )
    read_result = registry.invoke(
        ToolInvocation(
            action="record.read",
            input={"record_type": "activity", "record_id": "activity-1"},
        ),
        context,
    )

    assert result.records_changed == ["activity-1"]
    assert read_result.output["record"] == {
        "id": "activity-1",
        "note": "called buyer",
        "channel": "phone",
    }


def test_sales_create_followup_task_preserves_record_write_payload_shape() -> None:
    from backend.services.tools.local_records import reset_default_local_record_provider

    reset_default_local_record_provider()
    registry = get_default_action_registry(rebuild=True)
    context = _context()

    result = registry.invoke(
        ToolInvocation(
            action="sales.create_followup_task",
            input={
                "record_type": "task",
                "record_id": "task-1",
                "data": {"title": "Follow up", "due": "2026-06-06"},
            },
        ),
        context,
    )
    read_result = registry.invoke(
        ToolInvocation(
            action="record.read",
            input={"record_type": "task", "record_id": "task-1"},
        ),
        context,
    )

    assert result.records_changed == ["task-1"]
    assert read_result.output["record"] == {
        "id": "task-1",
        "title": "Follow up",
        "due": "2026-06-06",
    }
