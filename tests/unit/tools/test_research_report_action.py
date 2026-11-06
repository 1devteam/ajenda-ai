import uuid

from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation
from backend.services.tools.standalone_actions import research_synthesize_report


def test_research_report_synthesizes_only_upstream_evidence() -> None:
    result = research_synthesize_report(
        ToolInvocation(
            action="research.synthesize_report",
            input={
                "objective": "Compare competitors",
                "prospects": [
                    {
                        "company": "Example",
                        "website": "https://example.test",
                        "research_summary": "Observed search summary",
                        "identity_status": "unverified",
                        "sources": ["https://example.test/source"],
                    }
                ],
            },
        ),
        ActionRuntimeContext(
            tenant_id="tenant-1",
            task_id=uuid.uuid4(),
            mission_id=uuid.uuid4(),
            worker_id="worker-1",
            lease_id="lease-1",
        ),
    )

    report = result.output["research_report"]
    assert report["comparison"][0]["summary"] == "Observed search summary"
    assert report["source_urls"] == ["https://example.test/source"]
    assert report["market_opportunities"] == []
    assert "unverified" in result.limitations[0]
    assert result.records_changed == []
    assert result.evidence


def test_research_report_preserves_proven_valid_empty_without_inventing_opportunities() -> None:
    result = research_synthesize_report(
        ToolInvocation(
            action="research.synthesize_report",
            input={
                "objective": "Compare competitors",
                "prospects": [],
                "binding_required": True,
                "valid_empty_upstream": [
                    {
                        "classification": "valid_empty",
                        "reason": "public identity verification rejected all candidate sources",
                        "source_task_id": "task-1",
                        "source_action": "research.verify_public_candidates",
                    }
                ],
            },
        ),
        ActionRuntimeContext(
            tenant_id="tenant-1",
            task_id=uuid.uuid4(),
            mission_id=uuid.uuid4(),
            worker_id="worker-1",
            lease_id="lease-1",
        ),
    )

    report = result.output["research_report"]
    assert report["comparison"] == []
    assert report["market_opportunities"] == []
    assert report["evidence_gaps"] == ["public identity verification rejected all candidate sources"]
    assert report["result_semantics"] == "valid_empty"
