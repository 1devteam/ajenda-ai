from __future__ import annotations

import uuid

import pytest

from backend.services.tools.local_records import LocalRecordProvider
from backend.services.tools.sales_actions import (
    record_read,
    record_search,
    record_write,
    sales_create_followup_task,
    sales_draft_followup,
    sales_log_activity,
    sales_qualify,
    sales_recommend_next_action,
    sales_research,
    sales_score_lead,
)
from backend.services.tools.schemas import ActionExecutionContext, LocalRecord


def _context(provider: LocalRecordProvider) -> ActionExecutionContext:
    provider.seed(
        tenant_id="tenant-sales",
        records=[
            LocalRecord(
                tenant_id="tenant-sales",
                record_type="lead",
                record_id="lead-1",
                name="Acme Buyer",
                fields={"employee_count": 120, "budget": 25000, "urgency": "high", "decision_maker": True},
            )
        ],
    )
    return ActionExecutionContext(
        tenant_id="tenant-sales",
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker-sales",
        lease_id=str(uuid.uuid4()),
        session_factory=lambda: None,
        extras={"record_provider": provider},
    )


def test_record_search_and_read_return_evidence_shaped_output() -> None:
    context = _context(LocalRecordProvider())

    search = record_search({"record_type": "lead", "query": "Acme"}, context)
    read = record_read({"record_type": "lead", "record_id": "lead-1"}, context)

    assert search.output["count"] == 1
    assert search.evidence[0].evidence_source == "tool.invoke.record.search"
    assert read.output["record"]["name"] == "Acme Buyer"


def test_record_write_and_sales_write_actions_create_local_records() -> None:
    context = _context(LocalRecordProvider())

    created = record_write({"record_type": "contact", "name": "Ada", "fields": {"role": "CEO"}}, context)
    activity = sales_log_activity({"record_id": "lead-1", "activity_type": "call", "summary": "Intro call"}, context)
    followup = sales_create_followup_task({"record_id": "lead-1", "title": "Follow up"}, context)

    assert created.side_effect_class == "internal_write"
    assert activity.output["activity"]["record_type"] == "activity"
    assert followup.output["followup_task"]["record_type"] == "followup_task"


def test_sales_actions_research_score_qualify_and_recommend() -> None:
    context = _context(LocalRecordProvider())

    research = sales_research({"record_id": "lead-1"}, context)
    score = sales_score_lead({"record_id": "lead-1"}, context)
    qualify = sales_qualify({"record_id": "lead-1"}, context)
    recommendation = sales_recommend_next_action({"record_id": "lead-1"}, context)

    assert research.output["record"]["record_id"] == "lead-1"
    assert score.output["score"] == 100
    assert qualify.output["qualified"] is True
    assert recommendation.output["recommended_action"] == "schedule_discovery_call"


def test_sales_draft_followup_is_draft_only() -> None:
    context = _context(LocalRecordProvider())

    result = sales_draft_followup(
        {"recipient_name": "Ada", "company_name": "Acme", "topic": "pipeline automation"}, context
    )

    assert "Ada" in result.output["draft"]
    assert result.output["external_send_authorized"] is False


def test_record_provider_failure_is_propagated() -> None:
    context = _context(LocalRecordProvider())

    with pytest.raises(ValueError, match="simulated local record provider failure"):
        record_search({"record_type": "lead", "simulate_provider_failure": True}, context)
