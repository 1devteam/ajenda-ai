from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from backend.domain.enums import ComplianceCategory
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission

logger = logging.getLogger(__name__)

@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason: str

class PolicyGuardian:
    """Enforces governance and compliance policies on all workflows.
    
    Acts as the final check before a task or mission is allowed to transition
    into a running state. It enforces jurisdictional compliance, disclosure
    requirements, and human-review constraints based on the task's
    ComplianceCategory.
    """

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
        """Evaluate if a mission is compliant and allowed to run."""
        # Baseline operational missions are always allowed
        if mission.compliance_category == ComplianceCategory.OPERATIONAL:
            return PolicyDecision(True, "Operational mission allowed")
            
        # Check jurisdiction-specific policies
        return self._evaluate_jurisdiction_policy(
            mission.compliance_category, 
            mission.jurisdiction, 
            mission.metadata_json
        )

    def evaluate_task(self, task: ExecutionTask) -> PolicyDecision:
        """Evaluate if an execution task is compliant and allowed to run."""
        if task.compliance_category == ComplianceCategory.OPERATIONAL:
            return PolicyDecision(True, "Operational task allowed")
            
        # For employment or credit decisions, human review is mandatory
        if task.compliance_category in (ComplianceCategory.EMPLOYMENT, ComplianceCategory.FINANCIAL):
            if not task.requires_human_review:
                reason = (
                    f"Policy violation: Task {task.id} in category {task.compliance_category} "
                    "requires human review but requires_human_review is False."
                )
                logger.warning(reason)
                return PolicyDecision(False, reason)
                
        return self._evaluate_jurisdiction_policy(
            task.compliance_category,
            task.jurisdiction,
            task.metadata_json
        )

    def _evaluate_jurisdiction_policy(self, category: str, jurisdiction: str, metadata: dict[str, Any]) -> PolicyDecision:
        """Evaluate specific jurisdictional compliance requirements."""
        
        # EU AI Act (effective 2026/2027)
        if jurisdiction.startswith("EU"):
            if category in (
                ComplianceCategory.EMPLOYMENT,
                ComplianceCategory.FINANCIAL,
                ComplianceCategory.HEALTHCARE,
            ):
                # High-risk AI system (EU AI Act Annex III): employment decisions,
                # credit scoring / financial services, and healthcare diagnostics
                # all require explicit technical documentation reference.
                if "eu_technical_doc_ref" not in metadata:
                    reason = (
                        f"EU AI Act violation: High-risk category '{category}' "
                        "missing technical doc reference (Annex III)."
                    )
                    logger.warning(reason)
                    return PolicyDecision(False, reason)
            if category == ComplianceCategory.CONSUMER_INTERACTION:
                # Transparency requirement: users must be notified they are interacting with AI
                if not metadata.get("disclosure_provided", False):
                    reason = "EU AI Act violation: Consumer interaction missing AI disclosure."
                    logger.warning(reason)
                    return PolicyDecision(False, reason)

        # Colorado SB24-205 (effective Feb 2026)
        if jurisdiction == "US-CO":
            if category in (ComplianceCategory.EMPLOYMENT, ComplianceCategory.FINANCIAL, ComplianceCategory.HEALTHCARE):
                # Consequential decisions require disclosure and appeal path
                if not metadata.get("consequential_decision_disclosure", False):
                    reason = "Colorado SB24-205 violation: Consequential decision missing disclosure."
                    logger.warning(reason)
                    return PolicyDecision(False, reason)
                if not metadata.get("appeal_path_provided", False):
                    reason = "Colorado SB24-205 violation: Consequential decision missing appeal path."
                    logger.warning(reason)
                    return PolicyDecision(False, reason)

        # NYC Local Law 144 (Employment bias audit)
        if jurisdiction == "US-NY" and category == ComplianceCategory.EMPLOYMENT:
            if "bias_audit_date" not in metadata:
                reason = "NYC LL144 violation: Employment tool missing bias audit date."
                logger.warning(reason)
                return PolicyDecision(False, reason)

        # FTC / FCC Rules (CAN-SPAM / TCPA)
        if category == ComplianceCategory.MARKETING:
            if not metadata.get("opt_out_provided", False):
                reason = "FTC CAN-SPAM violation: Marketing workflow missing opt-out mechanism."
                logger.warning(reason)
                return PolicyDecision(False, reason)
            if metadata.get("uses_ai_voice", False) and not metadata.get("prior_express_consent", False):
                reason = "FCC TCPA violation: AI voice outreach missing prior express consent."
                logger.warning(reason)
                return PolicyDecision(False, reason)

        return PolicyDecision(True, "Jurisdictional compliance checks passed")
