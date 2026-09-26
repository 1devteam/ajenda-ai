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
    assert result.output["verified_prospect_candidates"][0]["identity_status"] == "verified"
    assert result.output["pages"][0]["url"].startswith("fixture://")
    assert result.output["pages"][0]["real"] is False
    assert result.output["verified_prospect_candidates"][0]["real"] is False
    assert result.output["verified_prospect_candidates"][0]["identity_evidence_urls"] == ["fixture://fixture-1"]


def test_observe_contacts_preserves_internal_crm_identity_without_contact_fields() -> None:
    result = research_observe_contacts(
        ToolInvocation(
            action="research.observe_contacts",
            input={
                "prospects": [
                    {
                        "prospect_id": "crm-1",
                        "company": "CRM Software Co",
                        "industry": "software development",
                        "location": "Austin",
                    }
                ],
                "requested_quantity": 1,
                "binding_required": True,
                "local_fixture_only": True,
                "context": {"source": "internal_crm"},
            },
        ),
        ActionRuntimeContext(tenant_id=str(uuid4()), task_id=uuid4(), worker_id=str(uuid4()), lease_id=str(uuid4())),
    )
    # Identity is preserved for diagnosis, but the contact-observation
    # contract remains unmet when the CRM record has no contact field.
    assert result.output["accept_met"] is False
    assert result.output["verified_prospect_candidates"][0]["source"] == "internal_crm"
    assert result.output["verified_prospect_candidates"][0]["identity_status"] == "verified"
    assert result.output["observed_contacts"] == []
