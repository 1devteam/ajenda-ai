"""Compliance test suite for PolicyGuardian.

Tests cover all regulatory domains implemented in the compliance layer:
- EU AI Act (high-risk systems, transparency, technical documentation)
- Colorado SB24-205 (consequential decisions, disclosure, appeal paths)
- NYC Local Law 144 (employment bias audit requirement)
- FTC CAN-SPAM (opt-out requirement for marketing)
- FCC TCPA (prior express consent for AI voice outreach)
- Cross-jurisdiction switching
- Adversarial misuse (missing fields, empty metadata, wrong types)
- Human review enforcement for employment and financial categories
"""
from __future__ import annotations
from unittest.mock import MagicMock
import pytest
from backend.domain.enums import ComplianceCategory, ExecutionTaskState
from backend.services.policy_guardian import PolicyDecision, PolicyGuardian


def _guardian() -> PolicyGuardian:
    """Build a PolicyGuardian with a mock DB session."""
    return PolicyGuardian(session=MagicMock())


def _task(
    category: str = ComplianceCategory.OPERATIONAL,
    jurisdiction: str = "US-ALL",
    requires_human_review: bool = False,
    metadata: dict | None = None,
) -> MagicMock:
    """Build a mock ExecutionTask with the given compliance fields."""
    task = MagicMock()
    task.id = "task-test-001"
    task.compliance_category = category
    task.jurisdiction = jurisdiction
    task.requires_human_review = requires_human_review
    task.metadata_json = metadata or {}
    task.status = ExecutionTaskState.PLANNED.value
    return task


def _mission(
    category: str = ComplianceCategory.OPERATIONAL,
    jurisdiction: str = "US-ALL",
    metadata: dict | None = None,
) -> MagicMock:
    """Build a mock Mission with the given compliance fields."""
    mission = MagicMock()
    mission.id = "mission-test-001"
    mission.compliance_category = category
    mission.jurisdiction = jurisdiction
    mission.metadata_json = metadata or {}
    return mission


# ─────────────────────────────────────────────────────────────────────────────
# BASELINE: Operational tasks are always allowed
# ─────────────────────────────────────────────────────────────────────────────

class TestOperationalBaseline:
    def test_operational_task_is_always_allowed(self) -> None:
        """Operational tasks bypass all compliance checks."""
        guardian = _guardian()
        task = _task(category=ComplianceCategory.OPERATIONAL)
        decision = guardian.evaluate_task(task)
        assert decision.allowed is True

    def test_operational_mission_is_always_allowed(self) -> None:
        """Operational missions bypass all compliance checks."""
        guardian = _guardian()
        mission = _mission(category=ComplianceCategory.OPERATIONAL)
        decision = guardian.evaluate_mission(mission)
        assert decision.allowed is True

    def test_operational_with_eu_jurisdiction_is_allowed(self) -> None:
        """Operational tasks in EU jurisdiction are still allowed — category drives policy."""
        guardian = _guardian()
        task = _task(category=ComplianceCategory.OPERATIONAL, jurisdiction="EU-DE")
        decision = guardian.evaluate_task(task)
        assert decision.allowed is True


# ─────────────────────────────────────────────────────────────────────────────
# HUMAN REVIEW ENFORCEMENT
# ─────────────────────────────────────────────────────────────────────────────

class TestHumanReviewEnforcement:
    def test_employment_task_without_human_review_is_blocked(self) -> None:
        """Employment tasks MUST have requires_human_review=True."""
        guardian = _guardian()
        task = _task(category=ComplianceCategory.EMPLOYMENT, requires_human_review=False)
        decision = guardian.evaluate_task(task)
        assert decision.allowed is False
        assert "human review" in decision.reason.lower()

    def test_financial_task_without_human_review_is_blocked(self) -> None:
        """Financial tasks MUST have requires_human_review=True."""
        guardian = _guardian()
        task = _task(category=ComplianceCategory.FINANCIAL, requires_human_review=False)
        decision = guardian.evaluate_task(task)
        assert decision.allowed is False
        assert "human review" in decision.reason.lower()

    def test_employment_task_with_human_review_passes_baseline(self) -> None:
        """Employment task with requires_human_review=True passes the baseline check."""
        guardian = _guardian()
        task = _task(
            category=ComplianceCategory.EMPLOYMENT,
            jurisdiction="US-ALL",
            requires_human_review=True,
        )
        decision = guardian.evaluate_task(task)
        # US-ALL has no additional requirements beyond human review
        assert decision.allowed is True

    def test_healthcare_task_without_human_review_passes_baseline(self) -> None:
        """Healthcare tasks do not require human review at the baseline level (only in specific jurisdictions)."""
        guardian = _guardian()
        task = _task(
            category=ComplianceCategory.HEALTHCARE,
            jurisdiction="US-ALL",
            requires_human_review=False,
        )
        decision = guardian.evaluate_task(task)
        assert decision.allowed is True


# ─────────────────────────────────────────────────────────────────────────────
# EU AI ACT
# ─────────────────────────────────────────────────────────────────────────────

class TestEuAiAct:
    def test_eu_employment_without_technical_doc_is_blocked(self) -> None:
        """EU AI Act: High-risk employment system missing technical documentation is blocked."""
        guardian = _guardian()
        task = _task(
            category=ComplianceCategory.EMPLOYMENT,
            jurisdiction="EU-DE",
            requires_human_review=True,
            metadata={},  # Missing eu_technical_doc_ref
        )
        decision = guardian.evaluate_task(task)
        assert decision.allowed is False
        assert "EU AI Act" in decision.reason

    def test_eu_employment_with_technical_doc_is_allowed(self) -> None:
        """EU AI Act: High-risk employment system with technical doc reference is allowed."""
        guardian = _guardian()
        task = _task(
            category=ComplianceCategory.EMPLOYMENT,
            jurisdiction="EU-DE",
            requires_human_review=True,
            metadata={"eu_technical_doc_ref": "TSD-2026-001"},
        )
        decision = guardian.evaluate_task(task)
        assert decision.allowed is True

    def test_eu_healthcare_without_technical_doc_is_blocked(self) -> None:
        """EU AI Act: Healthcare (high-risk) missing technical doc is blocked."""
        guardian = _guardian()
        task = _task(
            category=ComplianceCategory.HEALTHCARE,
            jurisdiction="EU-FR",
            metadata={},
        )
        decision = guardian.evaluate_task(task)
        assert decision.allowed is False
        assert "EU AI Act" in decision.reason

    def test_eu_consumer_interaction_without_disclosure_is_blocked(self) -> None:
        """EU AI Act: Consumer interaction without AI disclosure is blocked."""
        guardian = _guardian()
        task = _task(
            category=ComplianceCategory.CONSUMER_INTERACTION,
            jurisdiction="EU-NL",
            metadata={"disclosure_provided": False},
        )
        decision = guardian.evaluate_task(task)
        assert decision.allowed is False
        assert "EU AI Act" in decision.reason

    def test_eu_consumer_interaction_with_disclosure_is_allowed(self) -> None:
        """EU AI Act: Consumer interaction with AI disclosure is allowed."""
        guardian = _guardian()
        task = _task(
            category=ComplianceCategory.CONSUMER_INTERACTION,
            jurisdiction="EU-NL",
            metadata={"disclosure_provided": True},
        )
        decision = guardian.evaluate_task(task)
        assert decision.allowed is True

    def test_eu_marketing_without_opt_out_is_blocked(self) -> None:
        """EU jurisdiction + marketing category still enforces FTC opt-out rule."""
        guardian = _guardian()
        task = _task(
            category=ComplianceCategory.MARKETING,
            jurisdiction="EU-DE",
            metadata={},
        )
        decision = guardian.evaluate_task(task)
        assert decision.allowed is False

    def test_eu_operational_is_always_allowed(self) -> None:
        """EU operational tasks bypass all compliance checks."""
        guardian = _guardian()
        task = _task(category=ComplianceCategory.OPERATIONAL, jurisdiction="EU-DE")
        decision = guardian.evaluate_task(task)
        assert decision.allowed is True


# ─────────────────────────────────────────────────────────────────────────────
# COLORADO SB24-205
# ─────────────────────────────────────────────────────────────────────────────

class TestColoradoSB24205:
    def test_co_employment_without_disclosure_is_blocked(self) -> None:
        """Colorado SB24-205: Consequential employment decision missing disclosure is blocked."""
        guardian = _guardian()
        task = _task(
            category=ComplianceCategory.EMPLOYMENT,
            jurisdiction="US-CO",
            requires_human_review=True,
            metadata={"appeal_path_provided": True},  # Missing consequential_decision_disclosure
        )
        decision = guardian.evaluate_task(task)
        assert decision.allowed is False
        assert "Colorado" in decision.reason

    def test_co_employment_without_appeal_path_is_blocked(self) -> None:
        """Colorado SB24-205: Consequential employment decision missing appeal path is blocked."""
        guardian = _guardian()
        task = _task(
            category=ComplianceCategory.EMPLOYMENT,
            jurisdiction="US-CO",
            requires_human_review=True,
            metadata={"consequential_decision_disclosure": True},  # Missing appeal_path_provided
        )
        decision = guardian.evaluate_task(task)
        assert decision.allowed is False
        assert "Colorado" in decision.reason

    def test_co_employment_fully_compliant_is_allowed(self) -> None:
        """Colorado SB24-205: Fully compliant employment task is allowed."""
        guardian = _guardian()
        task = _task(
            category=ComplianceCategory.EMPLOYMENT,
            jurisdiction="US-CO",
            requires_human_review=True,
            metadata={
                "consequential_decision_disclosure": True,
                "appeal_path_provided": True,
            },
        )
        decision = guardian.evaluate_task(task)
        assert decision.allowed is True

    def test_co_financial_requires_disclosure_and_appeal(self) -> None:
        """Colorado SB24-205: Financial decisions also require disclosure and appeal path."""
        guardian = _guardian()
        task = _task(
            category=ComplianceCategory.FINANCIAL,
            jurisdiction="US-CO",
            requires_human_review=True,
            metadata={},
        )
        decision = guardian.evaluate_task(task)
        assert decision.allowed is False
        assert "Colorado" in decision.reason

    def test_co_healthcare_requires_disclosure_and_appeal(self) -> None:
        """Colorado SB24-205: Healthcare decisions require disclosure and appeal path."""
        guardian = _guardian()
        task = _task(
            category=ComplianceCategory.HEALTHCARE,
            jurisdiction="US-CO",
            metadata={},
        )
        decision = guardian.evaluate_task(task)
        assert decision.allowed is False
        assert "Colorado" in decision.reason


# ─────────────────────────────────────────────────────────────────────────────
# NYC LOCAL LAW 144
# ─────────────────────────────────────────────────────────────────────────────

class TestNycLocalLaw144:
    def test_nyc_employment_without_bias_audit_is_blocked(self) -> None:
        """NYC LL144: Employment tool without bias audit date is blocked."""
        guardian = _guardian()
        task = _task(
            category=ComplianceCategory.EMPLOYMENT,
            jurisdiction="US-NY",
            requires_human_review=True,
            metadata={},  # Missing bias_audit_date
        )
        decision = guardian.evaluate_task(task)
        assert decision.allowed is False
        assert "NYC" in decision.reason or "LL144" in decision.reason

    def test_nyc_employment_with_bias_audit_is_allowed(self) -> None:
        """NYC LL144: Employment tool with bias audit date is allowed."""
        guardian = _guardian()
        task = _task(
            category=ComplianceCategory.EMPLOYMENT,
            jurisdiction="US-NY",
            requires_human_review=True,
            metadata={"bias_audit_date": "2026-01-15"},
        )
        decision = guardian.evaluate_task(task)
        assert decision.allowed is True

    def test_nyc_non_employment_does_not_require_bias_audit(self) -> None:
        """NYC LL144 only applies to employment tools — other categories are unaffected."""
        guardian = _guardian()
        task = _task(
            category=ComplianceCategory.MARKETING,
            jurisdiction="US-NY",
            metadata={"opt_out_provided": True},
        )
        decision = guardian.evaluate_task(task)
        assert decision.allowed is True


# ─────────────────────────────────────────────────────────────────────────────
# FTC CAN-SPAM / FCC TCPA
# ─────────────────────────────────────────────────────────────────────────────

class TestFtcCanSpamTcpa:
    def test_marketing_without_opt_out_is_blocked(self) -> None:
        """FTC CAN-SPAM: Marketing workflow without opt-out mechanism is blocked."""
        guardian = _guardian()
        task = _task(
            category=ComplianceCategory.MARKETING,
            jurisdiction="US-ALL",
            metadata={},
        )
        decision = guardian.evaluate_task(task)
        assert decision.allowed is False
        assert "CAN-SPAM" in decision.reason

    def test_marketing_with_opt_out_is_allowed(self) -> None:
        """FTC CAN-SPAM: Marketing workflow with opt-out mechanism is allowed."""
        guardian = _guardian()
        task = _task(
            category=ComplianceCategory.MARKETING,
            jurisdiction="US-ALL",
            metadata={"opt_out_provided": True},
        )
        decision = guardian.evaluate_task(task)
        assert decision.allowed is True

    def test_ai_voice_marketing_without_consent_is_blocked(self) -> None:
        """FCC TCPA: AI voice outreach without prior express consent is blocked."""
        guardian = _guardian()
        task = _task(
            category=ComplianceCategory.MARKETING,
            jurisdiction="US-ALL",
            metadata={
                "opt_out_provided": True,
                "uses_ai_voice": True,
                "prior_express_consent": False,
            },
        )
        decision = guardian.evaluate_task(task)
        assert decision.allowed is False
        assert "TCPA" in decision.reason

    def test_ai_voice_marketing_with_consent_is_allowed(self) -> None:
        """FCC TCPA: AI voice outreach with prior express consent is allowed."""
        guardian = _guardian()
        task = _task(
            category=ComplianceCategory.MARKETING,
            jurisdiction="US-ALL",
            metadata={
                "opt_out_provided": True,
                "uses_ai_voice": True,
                "prior_express_consent": True,
            },
        )
        decision = guardian.evaluate_task(task)
        assert decision.allowed is True

    def test_non_ai_voice_marketing_does_not_require_consent(self) -> None:
        """TCPA consent requirement only applies when uses_ai_voice=True."""
        guardian = _guardian()
        task = _task(
            category=ComplianceCategory.MARKETING,
            jurisdiction="US-ALL",
            metadata={
                "opt_out_provided": True,
                "uses_ai_voice": False,
            },
        )
        decision = guardian.evaluate_task(task)
        assert decision.allowed is True


# ─────────────────────────────────────────────────────────────────────────────
# JURISDICTION SWITCHING
# ─────────────────────────────────────────────────────────────────────────────

class TestJurisdictionSwitching:
    def test_same_task_allowed_in_us_all_blocked_in_eu(self) -> None:
        """The same employment task is allowed in US-ALL but blocked in EU without tech doc."""
        guardian = _guardian()

        task_us = _task(
            category=ComplianceCategory.EMPLOYMENT,
            jurisdiction="US-ALL",
            requires_human_review=True,
        )
        task_eu = _task(
            category=ComplianceCategory.EMPLOYMENT,
            jurisdiction="EU-DE",
            requires_human_review=True,
        )

        assert guardian.evaluate_task(task_us).allowed is True
        assert guardian.evaluate_task(task_eu).allowed is False

    def test_same_task_allowed_in_us_tx_blocked_in_us_co(self) -> None:
        """Employment task without appeal path is allowed in US-TX but blocked in US-CO."""
        guardian = _guardian()

        task_tx = _task(
            category=ComplianceCategory.EMPLOYMENT,
            jurisdiction="US-TX",
            requires_human_review=True,
        )
        task_co = _task(
            category=ComplianceCategory.EMPLOYMENT,
            jurisdiction="US-CO",
            requires_human_review=True,
            metadata={},
        )

        assert guardian.evaluate_task(task_tx).allowed is True
        assert guardian.evaluate_task(task_co).allowed is False

    def test_nyc_employment_blocked_but_us_ca_allowed(self) -> None:
        """NYC LL144 bias audit requirement does not apply to US-CA."""
        guardian = _guardian()

        task_ny = _task(
            category=ComplianceCategory.EMPLOYMENT,
            jurisdiction="US-NY",
            requires_human_review=True,
            metadata={},
        )
        task_ca = _task(
            category=ComplianceCategory.EMPLOYMENT,
            jurisdiction="US-CA",
            requires_human_review=True,
            metadata={},
        )

        assert guardian.evaluate_task(task_ny).allowed is False
        assert guardian.evaluate_task(task_ca).allowed is True


# ─────────────────────────────────────────────────────────────────────────────
# ADVERSARIAL MISUSE
# ─────────────────────────────────────────────────────────────────────────────

class TestAdversarialMisuse:
    def test_empty_metadata_blocks_regulated_categories(self) -> None:
        """Empty metadata blocks any regulated category in a regulated jurisdiction."""
        guardian = _guardian()
        for category in [
            ComplianceCategory.EMPLOYMENT,
            ComplianceCategory.FINANCIAL,
            ComplianceCategory.MARKETING,
        ]:
            task = _task(
                category=category,
                jurisdiction="EU-DE",
                requires_human_review=(category in (ComplianceCategory.EMPLOYMENT, ComplianceCategory.FINANCIAL)),
                metadata={},
            )
            decision = guardian.evaluate_task(task)
            assert decision.allowed is False, f"Expected {category} to be blocked with empty metadata in EU-DE"

    def test_false_values_in_metadata_are_treated_as_missing(self) -> None:
        """Explicit False values for required fields are treated as non-compliant."""
        guardian = _guardian()
        task = _task(
            category=ComplianceCategory.MARKETING,
            jurisdiction="US-ALL",
            metadata={"opt_out_provided": False},
        )
        decision = guardian.evaluate_task(task)
        assert decision.allowed is False

    def test_policy_decision_is_immutable(self) -> None:
        """PolicyDecision is a frozen dataclass — cannot be mutated after creation."""
        decision = PolicyDecision(allowed=True, reason="test")
        with pytest.raises(Exception):
            decision.allowed = False  # type: ignore[misc]

    def test_mission_evaluation_mirrors_task_evaluation(self) -> None:
        """Mission-level evaluation applies the same jurisdictional rules as task-level."""
        guardian = _guardian()
        mission = _mission(
            category=ComplianceCategory.EMPLOYMENT,
            jurisdiction="EU-DE",
            metadata={},
        )
        decision = guardian.evaluate_mission(mission)
        assert decision.allowed is False
        assert "EU AI Act" in decision.reason
