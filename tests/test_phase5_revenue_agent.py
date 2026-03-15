"""
Phase 5 Test Suite — The Revenue Agent (v6.4)

Tests cover:
  1.  LeadStatus enum values
  2.  OpportunityStage enum values
  3.  ProposalStatus enum values
  4.  LeadRecord dataclass defaults
  5.  OpportunityRecord dataclass defaults
  6.  ProposalRecord dataclass defaults
  7.  RevenueRunResult dataclass defaults
  8.  RevenueAgent.run_pipeline — happy path (mocked coordinator)
  9.  RevenueAgent.run_pipeline — qualification threshold filtering
  10. RevenueAgent.run_pipeline — no proposals when generate_proposals=False
  11. RevenueAgent.run_pipeline — graceful handling of discovery failure
  12. RevenueAgent.run_pipeline — graceful handling of qualification failure
  13. RevenueAgent._parse_json_list — clean JSON array
  14. RevenueAgent._parse_json_list — JSON in markdown fence
  15. RevenueAgent._parse_json_list — JSON wrapped in dict key
  16. RevenueAgent._parse_json_list — invalid JSON returns empty list
  17. RevenueAgent._parse_json_object — clean JSON object
  18. RevenueAgent._parse_json_object — JSON in markdown fence
  19. RevenueAgent._parse_json_object — invalid JSON returns empty dict
  20. RevenueAgent.get_pipeline_summary — correct metric structure
  21. Lead DB model — required columns present
  22. Opportunity DB model — required columns present
  23. Proposal DB model — required columns present
  24. Deal DB model — required columns present
  25. Phase 5 migration — revision chain is linear
  26. revenue route — LeadCreate validation (min_length)
  27. revenue route — QualifyLeadRequest validation
  28. revenue route — RevenueDashboard model fields

Built with Pride for Obex Blackvault.
"""

import sys
import types
from datetime import datetime
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers — stub heavy dependencies so tests run without the full stack
# ---------------------------------------------------------------------------


def _stub_module(name: str, **attrs) -> types.ModuleType:
    """Create a stub module and register it in sys.modules."""
    mod = types.ModuleType(name)
    for attr, val in attrs.items():
        setattr(mod, attr, val)
    sys.modules[name] = mod
    return mod


def _ensure_stubs():
    """
    Stub heavy optional dependencies that are not installed.

    Uses a try/import guard so that when the real library IS installed
    (e.g. cryptography, apscheduler) the real module is used and the stub
    is never injected.  This prevents test-order contamination where a stub
    registered here would shadow the real module for later test files.
    """

    def _stub_if_missing(name: str, **attrs) -> None:
        """Register a stub only when the module cannot be imported."""
        if name in sys.modules:
            return  # already loaded (real or stub) — leave it alone
        try:
            __import__(name)
        except ImportError:
            _stub_module(name, **attrs)

    # LangChain — may or may not be installed
    _stub_if_missing("langchain_core")
    _stub_if_missing(
        "langchain_core.messages",
        HumanMessage=MagicMock,
        SystemMessage=MagicMock,
    )

    # APScheduler — IS installed; do NOT stub so that CronTrigger remains real
    _stub_if_missing("apscheduler")
    _stub_if_missing("apscheduler.schedulers")
    _stub_if_missing("apscheduler.schedulers.asyncio", AsyncIOScheduler=MagicMock)
    _stub_if_missing("apscheduler.triggers")
    _stub_if_missing("apscheduler.triggers.cron", CronTrigger=MagicMock)
    _stub_if_missing("apscheduler.triggers.interval", IntervalTrigger=MagicMock)

    # Optional social / browser integrations
    _stub_if_missing("praw", Reddit=MagicMock)
    _stub_if_missing("tweepy", Client=MagicMock, API=MagicMock)
    _stub_if_missing("playwright")
    _stub_if_missing("playwright.async_api", async_playwright=MagicMock)

    # Cryptography — IS installed; do NOT stub so that AESGCM remains real
    _stub_if_missing("cryptography")
    _stub_if_missing("cryptography.hazmat")
    _stub_if_missing("cryptography.hazmat.primitives")
    _stub_if_missing(
        "cryptography.hazmat.primitives.ciphers",
        Cipher=MagicMock,
        algorithms=MagicMock,
        modes=MagicMock,
    )
    _stub_if_missing(
        "cryptography.hazmat.primitives.ciphers.aead",
        AESGCM=MagicMock,
    )
    _stub_if_missing("cryptography.hazmat.backends", default_backend=MagicMock)


_ensure_stubs()

# Now safe to import our modules
from backend.orchestration.revenue_agent import (  # noqa: E402
    LeadRecord,
    LeadStatus,
    OpportunityRecord,
    OpportunityStage,
    ProposalRecord,
    ProposalStatus,
    RevenueAgent,
    RevenueRunResult,
)


# ---------------------------------------------------------------------------
# RevenueAgent factory
# ---------------------------------------------------------------------------


def _make_agent(
    discovery_result: list = None,
    qualification_result: tuple = None,
    proposal_result: dict = None,
) -> RevenueAgent:
    """
    Build a RevenueAgent with a mocked WorkforceCoordinator.

    The coordinator's run() method is configured to return different responses
    based on the roles requested, simulating the three pipeline stages.
    """
    if discovery_result is None:
        discovery_result = [
            {
                "company_name": "Acme Corp",
                "website": "https://acme.example.com",
                "industry": "retail",
                "company_size": "smb",
                "location": "New York",
                "fit_reason": "Needs loss-prevention automation",
                "source_url": "https://acme.example.com",
            }
        ]

    if qualification_result is None:
        qualification_result = (
            0.85,  # score
            "Strong fit — SMB retail with clear pain point",  # notes
            "VP of Operations",  # contact_title
            25000.0,  # estimated_value
            0.7,  # probability
        )

    if proposal_result is None:
        proposal_result = {
            "title": "Citadel AI for Acme Corp",
            "executive_summary": "We can reduce shrinkage by 30%.",
            "body": "## Proposal\n\nFull proposal body here.",
            "call_to_action": "Schedule a 30-minute demo this week",
        }

    import json

    async def _mock_run(goal: str = "", tenant_id: str = "", roles=None, **kwargs):
        """Simulate coordinator returning different results per role."""
        roles = roles or []
        role_str = str(roles[0]) if roles else ""

        if "researcher" in role_str:
            return {"result": json.dumps(discovery_result), "status": "COMPLETED"}

        if "analyst" in role_str:
            score, notes, title, value, prob = qualification_result
            return {
                "result": json.dumps(
                    {
                        "qualification_score": score,
                        "qualification_notes": notes,
                        "contact_title": title,
                        "estimated_value": value,
                        "probability": prob,
                    }
                ),
                "status": "COMPLETED",
            }

        if "writer" in role_str:
            return {
                "result": json.dumps(proposal_result),
                "status": "COMPLETED",
            }

        return {"result": "", "status": "COMPLETED"}

    coordinator_mock = MagicMock()
    coordinator_mock.run = _mock_run

    return RevenueAgent(
        workforce_coordinator=coordinator_mock,
        qualification_threshold=0.6,
        max_leads_per_run=5,
    )


# ---------------------------------------------------------------------------
# 1. LeadStatus enum
# ---------------------------------------------------------------------------


def test_lead_status_values():
    assert LeadStatus.NEW == "new"
    assert LeadStatus.RESEARCHED == "researched"
    assert LeadStatus.QUALIFIED == "qualified"
    assert LeadStatus.CONVERTED == "converted"
    assert LeadStatus.DISQUALIFIED == "disqualified"


# ---------------------------------------------------------------------------
# 2. OpportunityStage enum
# ---------------------------------------------------------------------------


def test_opportunity_stage_values():
    assert OpportunityStage.DISCOVERY == "discovery"
    assert OpportunityStage.PROPOSAL == "proposal"
    assert OpportunityStage.NEGOTIATION == "negotiation"
    assert OpportunityStage.CLOSED_WON == "closed_won"
    assert OpportunityStage.CLOSED_LOST == "closed_lost"


# ---------------------------------------------------------------------------
# 3. ProposalStatus enum
# ---------------------------------------------------------------------------


def test_proposal_status_values():
    assert ProposalStatus.DRAFT == "draft"
    assert ProposalStatus.SENT == "sent"
    assert ProposalStatus.VIEWED == "viewed"
    assert ProposalStatus.ACCEPTED == "accepted"
    assert ProposalStatus.REJECTED == "rejected"
    assert ProposalStatus.EXPIRED == "expired"


# ---------------------------------------------------------------------------
# 4. LeadRecord dataclass defaults
# ---------------------------------------------------------------------------


def test_lead_record_defaults():
    lead = LeadRecord(
        id="lead_001",
        company_name="Test Corp",
        tenant_id="tenant_001",
    )
    assert lead.status == LeadStatus.NEW
    assert lead.qualification_score is None
    assert lead.research_data == {}
    assert lead.contact_email is None
    assert isinstance(lead.created_at, datetime)


# ---------------------------------------------------------------------------
# 5. OpportunityRecord dataclass defaults
# ---------------------------------------------------------------------------


def test_opportunity_record_defaults():
    opp = OpportunityRecord(
        id="opp_001",
        lead_id="lead_001",
        tenant_id="tenant_001",
        name="Test Opportunity",
    )
    assert opp.stage == OpportunityStage.DISCOVERY
    assert opp.estimated_value is None
    assert opp.probability is None
    assert opp.closed_at is None
    assert isinstance(opp.created_at, datetime)


# ---------------------------------------------------------------------------
# 6. ProposalRecord dataclass defaults
# ---------------------------------------------------------------------------


def test_proposal_record_defaults():
    proposal = ProposalRecord(
        id="prop_001",
        opportunity_id="opp_001",
        tenant_id="tenant_001",
        title="Test Proposal",
        body="Proposal body",
    )
    assert proposal.status == ProposalStatus.DRAFT
    assert proposal.version == 1
    assert proposal.sent_to_email is None
    assert isinstance(proposal.created_at, datetime)


# ---------------------------------------------------------------------------
# 7. RevenueRunResult dataclass defaults
# ---------------------------------------------------------------------------


def test_revenue_run_result_defaults():
    result = RevenueRunResult(
        run_id="rev_001",
        tenant_id="tenant_001",
        goal="Test pipeline",
    )
    assert result.leads_discovered == 0
    assert result.leads_qualified == 0
    assert result.total_pipeline_value == 0.0
    assert result.status == "running"
    assert result.leads == []
    assert result.errors == []
    assert result.completed_at is None


# ---------------------------------------------------------------------------
# 8. run_pipeline — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_pipeline_happy_path():
    agent = _make_agent()
    result = await agent.run_pipeline(
        goal="Find retail leads",
        tenant_id="tenant_001",
        value_proposition="AI-powered loss prevention",
        target_profile="SMB retail companies in the US",
        ideal_customer_profile="Retail companies with 10-500 employees facing shrinkage",
        generate_proposals=True,
        send_outreach=False,
    )
    assert result.status == "completed"
    assert result.leads_discovered == 1
    assert result.leads_qualified == 1
    assert result.leads_disqualified == 0
    assert result.opportunities_created == 1
    assert result.proposals_generated == 1
    assert result.total_pipeline_value == 25000.0
    assert len(result.leads) == 1
    assert result.leads[0].status == LeadStatus.QUALIFIED
    assert result.leads[0].qualification_score == 0.85
    assert result.completed_at is not None


# ---------------------------------------------------------------------------
# 9. run_pipeline — qualification threshold filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_pipeline_qualification_threshold():
    """Leads scoring below threshold should be DISQUALIFIED."""
    agent = _make_agent(qualification_result=(0.3, "Poor fit", None, None, None))
    result = await agent.run_pipeline(
        goal="Find retail leads",
        tenant_id="tenant_001",
        value_proposition="AI loss prevention",
        target_profile="SMB retail",
        ideal_customer_profile="Retail 10-500 employees",
    )
    assert result.leads_qualified == 0
    assert result.leads_disqualified == 1
    assert result.opportunities_created == 0
    assert result.proposals_generated == 0
    assert result.leads[0].status == LeadStatus.DISQUALIFIED
    assert result.total_pipeline_value == 0.0


# ---------------------------------------------------------------------------
# 10. run_pipeline — no proposals when generate_proposals=False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_pipeline_no_proposals():
    agent = _make_agent()
    result = await agent.run_pipeline(
        goal="Find retail leads",
        tenant_id="tenant_001",
        value_proposition="AI loss prevention",
        target_profile="SMB retail",
        ideal_customer_profile="Retail 10-500 employees",
        generate_proposals=False,
    )
    assert result.leads_qualified == 1
    assert result.proposals_generated == 0
    assert result.proposals == []


# ---------------------------------------------------------------------------
# 11. run_pipeline — graceful handling of discovery failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_pipeline_discovery_failure():
    """When discovery raises, pipeline should complete with 0 leads."""

    async def _fail_run(*args, **kwargs):
        raise RuntimeError("Coordinator unavailable")

    coordinator_mock = MagicMock()
    coordinator_mock.run = _fail_run

    agent = RevenueAgent(
        workforce_coordinator=coordinator_mock,
        qualification_threshold=0.6,
    )
    result = await agent.run_pipeline(
        goal="Find leads",
        tenant_id="tenant_001",
        value_proposition="AI",
        target_profile="SMB",
        ideal_customer_profile="Any",
    )
    # Discovery failure returns empty list — pipeline completes gracefully
    assert result.status == "completed"
    assert result.leads_discovered == 0
    assert result.leads_qualified == 0


# ---------------------------------------------------------------------------
# 12. run_pipeline — graceful handling of qualification failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_pipeline_qualification_failure():
    """When qualification raises for a lead, it should be skipped with error recorded."""
    import json

    async def _mock_run(goal="", tenant_id="", roles=None, **kwargs):
        roles = roles or []
        role_str = str(roles[0]) if roles else ""
        if "researcher" in role_str:
            return {
                "result": json.dumps(
                    [
                        {
                            "company_name": "Fail Corp",
                            "industry": "tech",
                            "company_size": "smb",
                        }
                    ]
                ),
                "status": "COMPLETED",
            }
        # Analyst raises
        raise RuntimeError("LLM quota exceeded")

    coordinator_mock = MagicMock()
    coordinator_mock.run = _mock_run

    agent = RevenueAgent(
        workforce_coordinator=coordinator_mock,
        qualification_threshold=0.6,
    )
    result = await agent.run_pipeline(
        goal="Find leads",
        tenant_id="tenant_001",
        value_proposition="AI",
        target_profile="SMB",
        ideal_customer_profile="Any",
    )
    assert result.status == "completed"
    assert result.leads_discovered == 1
    assert result.leads_qualified == 0
    assert len(result.errors) == 1
    assert "Qualification failed" in result.errors[0]


# ---------------------------------------------------------------------------
# 13. _parse_json_list — clean JSON array
# ---------------------------------------------------------------------------


def test_parse_json_list_clean():
    raw = '[{"company_name": "Acme"}, {"company_name": "Beta"}]'
    result = RevenueAgent._parse_json_list(raw)
    assert len(result) == 2
    assert result[0]["company_name"] == "Acme"


# ---------------------------------------------------------------------------
# 14. _parse_json_list — JSON in markdown fence
# ---------------------------------------------------------------------------


def test_parse_json_list_markdown_fence():
    raw = '```json\n[{"company_name": "Acme"}]\n```'
    result = RevenueAgent._parse_json_list(raw)
    assert len(result) == 1
    assert result[0]["company_name"] == "Acme"


# ---------------------------------------------------------------------------
# 15. _parse_json_list — JSON wrapped in dict key
# ---------------------------------------------------------------------------


def test_parse_json_list_wrapped_in_dict():
    raw = '{"companies": [{"company_name": "Acme"}, {"company_name": "Beta"}]}'
    result = RevenueAgent._parse_json_list(raw)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# 16. _parse_json_list — invalid JSON returns empty list
# ---------------------------------------------------------------------------


def test_parse_json_list_invalid():
    raw = "This is not JSON at all"
    result = RevenueAgent._parse_json_list(raw)
    assert result == []


# ---------------------------------------------------------------------------
# 17. _parse_json_object — clean JSON object
# ---------------------------------------------------------------------------


def test_parse_json_object_clean():
    raw = '{"qualification_score": 0.85, "qualification_notes": "Good fit"}'
    result = RevenueAgent._parse_json_object(raw)
    assert result["qualification_score"] == 0.85
    assert result["qualification_notes"] == "Good fit"


# ---------------------------------------------------------------------------
# 18. _parse_json_object — JSON in markdown fence
# ---------------------------------------------------------------------------


def test_parse_json_object_markdown_fence():
    raw = '```json\n{"qualification_score": 0.9}\n```'
    result = RevenueAgent._parse_json_object(raw)
    assert result["qualification_score"] == 0.9


# ---------------------------------------------------------------------------
# 19. _parse_json_object — invalid JSON returns empty dict
# ---------------------------------------------------------------------------


def test_parse_json_object_invalid():
    raw = "Not valid JSON"
    result = RevenueAgent._parse_json_object(raw)
    assert result == {}


# ---------------------------------------------------------------------------
# 20. get_pipeline_summary — correct metric structure
# ---------------------------------------------------------------------------


def test_get_pipeline_summary_structure():
    agent = _make_agent()
    result = RevenueRunResult(
        run_id="rev_test",
        tenant_id="tenant_001",
        goal="Test pipeline",
        leads_discovered=5,
        leads_qualified=3,
        leads_disqualified=2,
        opportunities_created=3,
        proposals_generated=3,
        proposals_sent=1,
        deals_closed=0,
        total_pipeline_value=75000.0,
        status="completed",
        completed_at=datetime.utcnow(),
    )
    summary = agent.get_pipeline_summary(result)
    assert summary["run_id"] == "rev_test"
    assert summary["status"] == "completed"
    assert summary["metrics"]["leads_discovered"] == 5
    assert summary["metrics"]["leads_qualified"] == 3
    assert summary["metrics"]["qualification_rate"] == 0.6
    assert summary["metrics"]["total_pipeline_value_usd"] == 75000.0
    assert "top_leads" in summary
    assert "errors" in summary
    assert summary["completed_at"] is not None


# ---------------------------------------------------------------------------
# 21. Lead DB model — required columns present
# ---------------------------------------------------------------------------


def test_lead_model_columns():
    from backend.database.models import Lead

    cols = {c.name for c in Lead.__table__.columns}
    required = {
        "id",
        "tenant_id",
        "created_by",
        "company_name",
        "contact_name",
        "contact_email",
        "contact_title",
        "contact_linkedin",
        "industry",
        "company_size",
        "status",
        "qualification_score",
        "qualification_notes",
        "research_data",
        "source",
        "estimated_value",
        "notes",
        "created_at",
        "updated_at",
    }
    assert required.issubset(cols), f"Missing Lead columns: {required - cols}"


# ---------------------------------------------------------------------------
# 22. Opportunity DB model — required columns present
# ---------------------------------------------------------------------------


def test_opportunity_model_columns():
    from backend.database.models import Opportunity

    cols = {c.name for c in Opportunity.__table__.columns}
    required = {
        "id",
        "tenant_id",
        "lead_id",
        "name",
        "estimated_value",
        "probability",
        "stage",
        "status",
        "close_reason",
        "actual_value",
        "closed_at",
        "created_at",
        "updated_at",
    }
    assert required.issubset(cols), f"Missing Opportunity columns: {required - cols}"


# ---------------------------------------------------------------------------
# 23. Proposal DB model — required columns present
# ---------------------------------------------------------------------------


def test_proposal_model_columns():
    from backend.database.models import Proposal

    cols = {c.name for c in Proposal.__table__.columns}
    required = {
        "id",
        "tenant_id",
        "opportunity_id",
        "title",
        "executive_summary",
        "body",
        "call_to_action",
        "status",
        "sent_via",
        "sent_to_email",
        "sent_to_linkedin",
        "response_received",
        "version",
        "created_at",
        "updated_at",
    }
    assert required.issubset(cols), f"Missing Proposal columns: {required - cols}"


# ---------------------------------------------------------------------------
# 24. Deal DB model — required columns present
# ---------------------------------------------------------------------------


def test_deal_model_columns():
    from backend.database.models import Deal

    cols = {c.name for c in Deal.__table__.columns}
    required = {
        "id",
        "tenant_id",
        "opportunity_id",
        "lead_id",
        "value",
        "currency",
        "payment_status",
        "closed_at",
        "created_at",
        "updated_at",
    }
    assert required.issubset(cols), f"Missing Deal columns: {required - cols}"


# ---------------------------------------------------------------------------
# 25. Phase 5 migration — revision chain is linear
# ---------------------------------------------------------------------------


def test_phase5_migration_chain():
    import importlib.util
    import os

    migration_path = os.path.join(
        "/home/ubuntu/fresh_repo",
        "alembic",
        "versions",
        "d4e5f6a7b8c9_add_sales_pipeline_tables.py",
    )
    spec = importlib.util.spec_from_file_location(
        "d4e5f6a7b8c9_add_sales_pipeline_tables", migration_path
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "d4e5f6a7b8c9"
    assert migration.down_revision == "c3d4e5f6a7b8"


# ---------------------------------------------------------------------------
# 26. revenue route — LeadCreate validation (min_length)
# ---------------------------------------------------------------------------


def test_lead_create_validation():
    from pydantic import ValidationError
    from backend.api.routes.revenue import LeadCreate

    # Empty company_name should fail
    with pytest.raises(ValidationError):
        LeadCreate(company_name="")

    # Valid lead
    lead = LeadCreate(
        company_name="Acme Corp",
        industry="retail",
        source="manual",
    )
    assert lead.company_name == "Acme Corp"
    assert lead.industry == "retail"
    assert lead.research_data == {}


# ---------------------------------------------------------------------------
# 27. revenue route — QualifyLeadRequest validation
# ---------------------------------------------------------------------------


def test_qualify_lead_request_validation():
    from pydantic import ValidationError
    from backend.api.routes.revenue import QualifyLeadRequest

    # Missing required fields
    with pytest.raises(ValidationError):
        QualifyLeadRequest()

    # Valid request
    req = QualifyLeadRequest(
        value_proposition="AI-powered loss prevention for retail",
        ideal_customer_profile="SMB retail companies with 10-500 employees",
    )
    assert "AI-powered" in req.value_proposition
    assert "SMB" in req.ideal_customer_profile


# ---------------------------------------------------------------------------
# 28. revenue route — RevenueDashboard model fields
# ---------------------------------------------------------------------------


def test_revenue_dashboard_model_fields():
    from backend.api.routes.revenue import RevenueDashboard

    dashboard = RevenueDashboard(
        total_leads=100,
        qualified_leads=60,
        open_opportunities=45,
        proposals_sent=30,
        deals_closed=10,
        total_revenue=250000.0,
        pipeline_value=1125000.0,
        conversion_rate=0.1,
        avg_deal_value=25000.0,
        top_industries=[{"industry": "retail", "count": 40}],
    )
    assert dashboard.total_leads == 100
    assert dashboard.qualified_leads == 60
    assert dashboard.total_revenue == 250000.0
    assert dashboard.conversion_rate == 0.1
    assert len(dashboard.top_industries) == 1
    assert dashboard.top_industries[0]["industry"] == "retail"
