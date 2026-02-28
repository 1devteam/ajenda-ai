"""
Governance Economy Integration Tests
Test risk-based pricing and compliance rewards

Built with Pride for Obex Blackvault
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.base import Base
from backend.database.governance_models import AssetType, RiskTier, ComplianceStatus
from backend.database.repositories import AssetRepository
from backend.economy.governance_economy import GovernanceEconomy

pytestmark = pytest.mark.unit


@pytest.fixture(scope="function")
def db_session():
    """Create test database session"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    yield session

    session.close()
    Base.metadata.drop_all(engine)


def test_mission_cost_minimal_risk(db_session):
    """Test mission cost calculation for minimal risk agent"""
    # Create minimal risk agent
    asset_repo = AssetRepository(db_session)
    asset = asset_repo.create_asset(
        id="minimal_agent",
        name="Minimal Risk Agent",
        asset_type=AssetType.AGENT,
        owner_id="user_1",
        tenant_id="tenant_1",
    )
    # Update risk tier separately
    asset_repo.update_risk_assessment("minimal_agent", RiskTier.MINIMAL, 0.1)

    # Calculate cost
    cost = GovernanceEconomy.calculate_mission_cost(
        base_cost=100.0, agent_id="minimal_agent", tenant_id="tenant_1", db=db_session
    )

    assert cost["governance_applied"] is True
    assert cost["risk_tier"] == "minimal"
    assert cost["risk_multiplier"] == 1.0
    assert cost["final_cost"] == 100.0


def test_mission_cost_high_risk(db_session):
    """Test mission cost calculation for high risk agent"""
    # Create high risk agent
    asset_repo = AssetRepository(db_session)
    asset = asset_repo.create_asset(
        id="high_risk_agent",
        name="High Risk Agent",
        asset_type=AssetType.AGENT,
        owner_id="user_1",
        tenant_id="tenant_1",
    )
    asset_repo.update_risk_assessment("high_risk_agent", RiskTier.HIGH, 0.7)

    # Calculate cost
    cost = GovernanceEconomy.calculate_mission_cost(
        base_cost=100.0, agent_id="high_risk_agent", tenant_id="tenant_1", db=db_session
    )

    assert cost["governance_applied"] is True
    assert cost["risk_tier"] == "high"
    assert cost["risk_multiplier"] == 1.5
    assert cost["final_cost"] == 150.0


def test_mission_cost_unacceptable_risk(db_session):
    """Test mission cost calculation for unacceptable risk agent"""
    # Create unacceptable risk agent
    asset_repo = AssetRepository(db_session)
    asset = asset_repo.create_asset(
        id="unacceptable_agent",
        name="Unacceptable Risk Agent",
        asset_type=AssetType.AGENT,
        owner_id="user_1",
        tenant_id="tenant_1",
    )
    asset_repo.update_risk_assessment("unacceptable_agent", RiskTier.UNACCEPTABLE, 0.95)

    # Calculate cost
    cost = GovernanceEconomy.calculate_mission_cost(
        base_cost=100.0,
        agent_id="unacceptable_agent",
        tenant_id="tenant_1",
        db=db_session,
    )

    assert cost["governance_applied"] is True
    assert cost["risk_tier"] == "unacceptable"
    assert cost["risk_multiplier"] == 2.0
    assert cost["final_cost"] == 200.0


def test_mission_cost_unregistered_agent(db_session):
    """Test mission cost for unregistered agent (no governance)"""
    cost = GovernanceEconomy.calculate_mission_cost(
        base_cost=100.0,
        agent_id="nonexistent_agent",
        tenant_id="tenant_1",
        db=db_session,
    )

    assert cost["governance_applied"] is False
    assert cost["final_cost"] == 100.0


def test_compliance_reward_compliant(db_session):
    """Test compliance reward for compliant agent"""
    # Create compliant agent
    asset_repo = AssetRepository(db_session)
    asset = asset_repo.create_asset(
        id="compliant_agent",
        name="Compliant Agent",
        asset_type=AssetType.AGENT,
        owner_id="user_1",
        tenant_id="tenant_1",
    )
    asset_repo.update_compliance_status("compliant_agent", ComplianceStatus.COMPLIANT)

    # Calculate reward
    reward = GovernanceEconomy.calculate_compliance_reward(
        agent_id="compliant_agent", tenant_id="tenant_1", db=db_session
    )

    assert reward["compliance_status"] == "compliant"
    assert reward["reward"] == 10.0
    assert reward["reason"] == "compliance_reward"


def test_compliance_penalty_non_compliant(db_session):
    """Test compliance penalty for non-compliant agent"""
    # Create non-compliant agent
    asset_repo = AssetRepository(db_session)
    asset = asset_repo.create_asset(
        id="non_compliant_agent",
        name="Non-Compliant Agent",
        asset_type=AssetType.AGENT,
        owner_id="user_1",
        tenant_id="tenant_1",
    )
    asset_repo.update_compliance_status("non_compliant_agent", ComplianceStatus.NON_COMPLIANT)

    # Calculate penalty
    reward = GovernanceEconomy.calculate_compliance_reward(
        agent_id="non_compliant_agent", tenant_id="tenant_1", db=db_session
    )

    assert reward["compliance_status"] == "non_compliant"
    assert reward["reward"] == -20.0
    assert reward["reason"] == "compliance_penalty"


def test_approval_cost_minimal_risk():
    """Test approval cost for minimal risk operation"""
    cost = GovernanceEconomy.calculate_approval_cost(
        request_type="deployment", risk_tier=RiskTier.MINIMAL
    )

    # Base deployment cost (50) * minimal multiplier (1.0)
    assert cost == 50.0


def test_approval_cost_high_risk():
    """Test approval cost for high risk operation"""
    cost = GovernanceEconomy.calculate_approval_cost(
        request_type="deployment", risk_tier=RiskTier.HIGH
    )

    # Base deployment cost (50) * high risk multiplier (1.5)
    assert cost == 75.0


def test_policy_violation_penalty_low_severity():
    """Test penalty for low severity violation"""
    penalty = GovernanceEconomy.calculate_policy_violation_penalty(
        severity="low", violation_count=1
    )

    # Base low penalty (10) * escalation (1.5 for 1 violation)
    assert penalty == 15.0


def test_policy_violation_penalty_critical_repeated():
    """Test penalty for repeated critical violations"""
    penalty = GovernanceEconomy.calculate_policy_violation_penalty(
        severity="critical", violation_count=3
    )

    # Base critical penalty (500) * escalation (2.5 for 3 violations)
    assert penalty == 1250.0


def test_pricing_summary(db_session):
    """Test pricing summary for agent"""
    # Create agent with risk and compliance
    asset_repo = AssetRepository(db_session)
    asset = asset_repo.create_asset(
        id="summary_agent",
        name="Summary Agent",
        asset_type=AssetType.AGENT,
        owner_id="user_1",
        tenant_id="tenant_1",
    )
    asset_repo.update_risk_assessment("summary_agent", RiskTier.HIGH, 0.7)
    asset_repo.update_compliance_status("summary_agent", ComplianceStatus.COMPLIANT)

    # Get pricing summary
    summary = GovernanceEconomy.get_pricing_summary(
        agent_id="summary_agent", tenant_id="tenant_1", db=db_session
    )

    assert summary["registered"] is True
    assert summary["risk_tier"] == "high"
    assert summary["risk_multiplier"] == 1.5
    assert summary["compliance_status"] == "compliant"
    assert summary["compliance_reward"] == 10.0
    assert "example_costs" in summary
    assert summary["example_costs"]["base_mission_100_credits"] == 150.0


def test_economic_incentives_alignment(db_session):
    """Test that economic incentives align with governance goals"""
    asset_repo = AssetRepository(db_session)

    # Create agents with different risk/compliance profiles
    profiles = [
        ("low_risk_compliant", RiskTier.MINIMAL, ComplianceStatus.COMPLIANT),
        ("high_risk_compliant", RiskTier.HIGH, ComplianceStatus.COMPLIANT),
        ("low_risk_non_compliant", RiskTier.MINIMAL, ComplianceStatus.NON_COMPLIANT),
        ("high_risk_non_compliant", RiskTier.HIGH, ComplianceStatus.NON_COMPLIANT),
    ]

    results = []

    for agent_id, risk_tier, compliance_status in profiles:
        asset = asset_repo.create_asset(
            id=agent_id,
            name=f"Agent {agent_id}",
            asset_type=AssetType.AGENT,
            owner_id="user_1",
            tenant_id="tenant_1",
        )
        # Set risk and compliance separately
        risk_scores = {RiskTier.MINIMAL: 0.1, RiskTier.HIGH: 0.7}
        asset_repo.update_risk_assessment(agent_id, risk_tier, risk_scores[risk_tier])
        asset_repo.update_compliance_status(agent_id, compliance_status)

        cost = GovernanceEconomy.calculate_mission_cost(
            base_cost=100.0, agent_id=agent_id, tenant_id="tenant_1", db=db_session
        )

        reward = GovernanceEconomy.calculate_compliance_reward(
            agent_id=agent_id, tenant_id="tenant_1", db=db_session
        )

        net_cost = cost["final_cost"] - reward["reward"]

        results.append(
            {
                "agent_id": agent_id,
                "risk_tier": risk_tier.value,
                "compliance": compliance_status.value,
                "mission_cost": cost["final_cost"],
                "compliance_reward": reward["reward"],
                "net_cost": net_cost,
            }
        )

    # Verify incentive alignment:
    # 1. Lower risk should cost less
    assert results[0]["mission_cost"] < results[1]["mission_cost"]  # minimal < high

    # 2. Compliant should be cheaper (net cost)
    assert results[0]["net_cost"] < results[2]["net_cost"]  # compliant < non-compliant
    assert results[1]["net_cost"] < results[3]["net_cost"]

    # 3. Best case: low risk + compliant
    best_case = min(results, key=lambda x: x["net_cost"])
    assert best_case["agent_id"] == "low_risk_compliant"

    # 4. Worst case: high risk + non-compliant
    worst_case = max(results, key=lambda x: x["net_cost"])
    assert worst_case["agent_id"] == "high_risk_non_compliant"
