from uuid import uuid4

from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation
from backend.services.tools.web_actions import research_observe_contacts


def test_observe_contacts_uses_fixture_without_network() -> None:
    result = research_observe_contacts(
        ToolInvocation(
            action="research.observe_contacts",
            input={
                "prospects": [{"prospect_id": "fixture-1", "company": "Fixture Co", "email": "hello@fixture.test"}],
                "requested_quantity": 1,
                "binding_required": True,
                "local_fixture_only": True,
            },
        ),
        ActionRuntimeContext(tenant_id=str(uuid4()), task_id=uuid4(), worker_id=str(uuid4()), lease_id=str(uuid4())),
    )
    assert result.output["accept_met"] is True
    assert result.output["observed_contacts"][0]["via"] == "local_fixture"
    assert result.output["pages"][0]["url"].startswith("fixture://")
