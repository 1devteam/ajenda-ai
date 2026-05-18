from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from backend.domain.enums import ComplianceCategory, ComplianceJurisdiction
from backend.services.policy_guardian import PolicyGuardian


def _guardian() -> PolicyGuardian:
    return PolicyGuardian(session=MagicMock())


def _task(
    *,
    category: str = ComplianceCategory.OPERATIONAL.value,
    jurisdiction: str = ComplianceJurisdiction.GLOBAL.value,
    requires_human_review: bool = False,
    metadata: dict[str, Any] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        compliance_category=category,
        jurisdiction=jurisdiction,
        requires_human_review=requires_human_review,
        metadata_json=metadata or {},
    )


def _mission(
    *,
    category: str = ComplianceCategory.OPERATIONAL.value,
    jurisdiction: str = ComplianceJurisdiction.GLOBAL.value,
    metadata: dict[str, Any] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        compliance_category=category,
        jurisdiction=jurisdiction,
        metadata_json=metadata or {},
    )


def test_operational_task_is_allowed() -> None:
    decision = _guardian().evaluate_task(_task())

    assert decision.allowed is True


def test_employment_task_requires_human_review() -> None:
    decision = _guardian().evaluate_task(_task(category=ComplianceCategory.EMPLOYMENT.value))

    assert decision.allowed is False
    assert "Human review" in decision.reason


def test_eu_high_risk_task_requires_technical_documentation() -> None:
    decision = _guardian().evaluate_task(
        _task(
            category=ComplianceCategory.HEALTHCARE.value,
            jurisdiction=ComplianceJurisdiction.EU.value,
        )
    )

    assert decision.allowed is False
    assert "technical documentation" in decision.reason


def test_eu_high_risk_task_allows_technical_documentation() -> None:
    decision = _guardian().evaluate_task(
        _task(
            category=ComplianceCategory.HEALTHCARE.value,
            jurisdiction=ComplianceJurisdiction.EU.value,
            metadata={"technical_doc_ref": "doc-123"},
        )
    )

    assert decision.allowed is True


def test_colorado_consequential_decision_requires_disclosure_and_appeal() -> None:
    decision = _guardian().evaluate_task(
        _task(
            category=ComplianceCategory.FINANCIAL.value,
            jurisdiction=ComplianceJurisdiction.COLORADO.value,
            requires_human_review=True,
            metadata={"consequential_decision_disclosure": True},
        )
    )

    assert decision.allowed is False
    assert "appeal path" in decision.reason


def test_marketing_requires_opt_out() -> None:
    decision = _guardian().evaluate_task(_task(category=ComplianceCategory.MARKETING.value))

    assert decision.allowed is False
    assert "opt-out" in decision.reason


def test_mission_uses_same_compliance_contract() -> None:
    decision = _guardian().evaluate_mission(
        _mission(
            category=ComplianceCategory.CONSUMER_INTERACTION.value,
            jurisdiction=ComplianceJurisdiction.EU.value,
        )
    )

    assert decision.allowed is False
    assert "AI disclosure" in decision.reason
