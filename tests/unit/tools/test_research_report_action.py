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
    assert len(report["market_opportunities"]) == 3
    assert all(item["type"] == "hypothesis" for item in report["market_opportunities"])
    assert "unverified" in result.limitations[0]
    assert result.records_changed == []
    assert result.evidence
