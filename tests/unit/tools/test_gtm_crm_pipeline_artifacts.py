from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from backend.services.plugins.crm_client import CrmUpsertResult
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


def _result(data: dict, index: int) -> CrmUpsertResult:
    return CrmUpsertResult(
        record_type="contact",
        record_id=f"crm-{index}",
        data=data,
        source="external_crm",
        real=True,
        status="upserted_real",
        status_code=200,
    )


def test_crm_pipeline_consumes_qualified_and_prospect_artifacts() -> None:
    client = MagicMock()
    client.upsert.side_effect = lambda **kwargs: _result(kwargs["data"], client.upsert.call_count)
    registry = get_default_action_registry(rebuild=True)
    handler = registry.get("gtm.crm_upsert").handler
    invocation = ToolInvocation(
        action="gtm.crm_upsert",
        input={
            "record_type": "lead",
            "data": {"pipeline_stage": "qualified"},
            "context": {
                "prospect_candidates": [
                    {"prospect_id": "p1", "company": "Alpha HVAC", "domain": "alpha.example"},
                    {"prospect_id": "p2", "company": "Beta HVAC", "domain": "beta.example"},
                ],
                "qualified_prospects": [
                    {"prospect_id": "p1", "score": 91},
                    {"prospect_id": "p2", "score": 84},
                ],
            },
        },
        idempotency_key="pipeline-1",
    )

    with patch("backend.services.tools.gtm_action_crm.default_crm_client", return_value=client):
        result = handler(invocation, _context())

    assert client.upsert.call_count == 2
    first = client.upsert.call_args_list[0].kwargs
    second = client.upsert.call_args_list[1].kwargs
    assert first["data"] == {
        "prospect_id": "p1",
        "company": "Alpha HVAC",
        "domain": "alpha.example",
        "score": 91,
        "pipeline_stage": "qualified",
    }
    assert second["data"]["company"] == "Beta HVAC"
    assert first["invocation"].idempotency_key == "pipeline-1:row:1"
    assert second["invocation"].idempotency_key == "pipeline-1:row:2"
    assert result.output["record_count"] == 2
    assert result.output["source_artifact"] == "qualified_prospects"
    assert [row["data"]["prospect_id"] for row in result.output["pipeline_records"]] == ["p1", "p2"]
    assert result.records_changed == ["crm-1", "crm-2"]


def test_crm_pipeline_falls_back_to_bound_prospect_candidates() -> None:
    client = MagicMock()
    client.upsert.side_effect = lambda **kwargs: _result(kwargs["data"], 1)
    registry = get_default_action_registry(rebuild=True)
    handler = registry.get("gtm.crm_upsert").handler

    with patch("backend.services.tools.gtm_action_crm.default_crm_client", return_value=client):
        result = handler(
            ToolInvocation(
                action="gtm.crm_upsert",
                input={
                    "record_type": "lead",
                    "context": {"prospect_candidates": [{"prospect_id": "p1", "company": "Alpha HVAC"}]},
                },
            ),
            _context(),
        )

    assert client.upsert.call_args.kwargs["data"]["company"] == "Alpha HVAC"
    assert result.output["source_artifact"] == "prospect_candidates"
    assert result.output["pipeline_records"][0]["data"]["prospect_id"] == "p1"


def test_crm_pipeline_preserves_direct_manual_upsert() -> None:
    client = MagicMock()
    client.upsert.side_effect = lambda **kwargs: _result(kwargs["data"], 1)
    registry = get_default_action_registry(rebuild=True)
    handler = registry.get("gtm.crm_upsert").handler

    with patch("backend.services.tools.gtm_action_crm.default_crm_client", return_value=client):
        result = handler(
            ToolInvocation(
                action="gtm.crm_upsert",
                input={"record_type": "lead", "data": {"email": "lead@example.com"}},
            ),
            _context(),
        )

    client.upsert.assert_called_once()
    assert client.upsert.call_args.kwargs["data"] == {"email": "lead@example.com"}
    assert result.output["source_artifact"] == "direct_data"
    assert result.output["record_count"] == 1
