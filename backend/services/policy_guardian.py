from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from backend.domain.enums import ComplianceCategory, ComplianceJurisdiction
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason: str


class PolicyGuardian:
    """Foundational deny-by-default policy validator for protected actions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def validate_privileged_action(self, *, tenant_id: str, action: str) -> PolicyDecision:
        if not tenant_id.strip():
            return PolicyDecision(False, "tenant_id is required")
        return PolicyDecision(
            allowed=False,
            reason=f"Privileged action '{action}' is not enabled in Phase 1 foundation.",
        )

    def evaluate_mission(self, mission: Mission) -> PolicyDecision:
        return self._evaluate_compliance(
            category=mission.compliance_category,
            jurisdiction=mission.jurisdiction,
            metadata=mission.metadata_json,
            requires_human_review=False,
        )

    def evaluate_task(self, task: ExecutionTask) -> PolicyDecision:
        return self._evaluate_compliance(
            category=task.compliance_category,
            jurisdiction=task.jurisdiction,
            metadata=task.metadata_json,
            requires_human_review=task.requires_human_review,
        )

    def _evaluate_compliance(
        self,
        *,
        category: str,
        jurisdiction: str,
        metadata: dict[str, Any],
        requires_human_review: bool,
    ) -> PolicyDecision:
        if category == ComplianceCategory.OPERATIONAL.value:
            return PolicyDecision(True, "Operational workflow allowed")

        if (
            category
            in {
                ComplianceCategory.EMPLOYMENT.value,
                ComplianceCategory.FINANCIAL.value,
            }
            and not requires_human_review
        ):
            return PolicyDecision(
                False,
                "Human review is required for employment or financial workflows.",
            )

        if jurisdiction == ComplianceJurisdiction.EU.value:
            return self._evaluate_eu_policy(category=category, metadata=metadata)

        if jurisdiction == ComplianceJurisdiction.COLORADO.value:
            return self._evaluate_colorado_policy(category=category, metadata=metadata)

        if jurisdiction == ComplianceJurisdiction.NYC.value:
            return self._evaluate_nyc_policy(category=category, metadata=metadata)

        if category == ComplianceCategory.MARKETING.value:
            return self._evaluate_marketing_policy(metadata=metadata)

        return PolicyDecision(True, "Compliance checks passed")

    def _evaluate_eu_policy(
        self,
        *,
        category: str,
        metadata: dict[str, Any],
    ) -> PolicyDecision:
        if category in {
            ComplianceCategory.EMPLOYMENT.value,
            ComplianceCategory.FINANCIAL.value,
            ComplianceCategory.HEALTHCARE.value,
        } and not metadata.get("technical_doc_ref"):
            return PolicyDecision(
                False,
                "EU high-risk workflow requires technical documentation reference.",
            )

        if category == ComplianceCategory.CONSUMER_INTERACTION.value and not metadata.get(
            "ai_disclosure_provided"
        ):
            return PolicyDecision(
                False,
                "EU consumer interaction workflow requires AI disclosure.",
            )

        return PolicyDecision(True, "EU compliance checks passed")

    def _evaluate_colorado_policy(
        self,
        *,
        category: str,
        metadata: dict[str, Any],
    ) -> PolicyDecision:
        if category not in {
            ComplianceCategory.EMPLOYMENT.value,
            ComplianceCategory.FINANCIAL.value,
            ComplianceCategory.HEALTHCARE.value,
        }:
            return PolicyDecision(True, "Colorado compliance checks passed")

        if not metadata.get("consequential_decision_disclosure"):
            return PolicyDecision(
                False,
                "Colorado consequential decision workflow requires disclosure.",
            )

        if not metadata.get("appeal_path_provided"):
            return PolicyDecision(
                False,
                "Colorado consequential decision workflow requires appeal path.",
            )

        return PolicyDecision(True, "Colorado compliance checks passed")

    def _evaluate_nyc_policy(
        self,
        *,
        category: str,
        metadata: dict[str, Any],
    ) -> PolicyDecision:
        if category == ComplianceCategory.EMPLOYMENT.value and not metadata.get("bias_audit_date"):
            return PolicyDecision(
                False,
                "NYC employment workflow requires bias audit date.",
            )

        return PolicyDecision(True, "NYC compliance checks passed")

    def _evaluate_marketing_policy(self, *, metadata: dict[str, Any]) -> PolicyDecision:
        if not metadata.get("opt_out_mechanism"):
            return PolicyDecision(
                False,
                "Marketing workflow requires opt-out mechanism.",
            )

        if metadata.get("uses_ai_voice") and not metadata.get("ai_voice_consent"):
            return PolicyDecision(
                False,
                "AI voice marketing workflow requires prior consent.",
            )

        return PolicyDecision(True, "Marketing compliance checks passed")
