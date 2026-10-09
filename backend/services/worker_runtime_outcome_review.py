from typing import Any

from backend.domain.execution_task import ExecutionTask
from backend.domain.outcome_review import OutcomeReview
from backend.repositories.outcome_review_repository import OutcomeReviewRepository


def gtm_side_effect_was_real(service, task_output: dict[str, Any]) -> bool:
    nested = task_output.get("output")
    if isinstance(nested, dict) and "real" in nested:
        return bool(nested.get("real"))
    return bool(task_output.get("real"))

def is_high_risk_gtm_side_effect(service, task: ExecutionTask, task_output: dict[str, Any] | None) -> bool:
    if not task_output or not isinstance(task_output, dict):
        return False
    action = str(task_output.get("action", "") or "")
    side_effect_class = str(task_output.get("side_effect_class", "") or "")
    if not action.startswith("gtm."):
        return False
    if side_effect_class not in {"external_send", "external_write", "external_publish"}:
        return False
    return gtm_side_effect_was_real(service, task_output)

def create_draft_outcome_review(
    service,
    *,
    task: ExecutionTask,
    task_output: dict[str, Any],
    evidence_ids: list[str],
) -> None:
    """Create a draft OutcomeReview for high-risk GTM side-effect completion.

    Populates from task metadata (side_effect_authorization from PR9 launch) and
    the just-collected evidence. Idempotent-ish: skips if recent draft exists for mission.
    """
    try:
        repo = OutcomeReviewRepository(service._session)
        existing = repo.list_for_mission(mission_id=task.mission_id, tenant_id=task.tenant_id)
        for r in existing:
            if r.review_status in ("draft", "in_review"):
                return  # already has active review

        metadata = task.metadata_json or {}
        tool_inv = metadata.get("tool_invocation", {}) or {}
        auth = (metadata.get("execution_constraints") or {}).get("side_effect_authorization", {}) or {}
        approved_by = auth.get("approved_by") or "system"
        reason = auth.get("reason") or "High-risk GTM side effect completed"

        action_name = tool_inv.get("action") or task_output.get("action", "gtm.unknown")

        review = OutcomeReview(
            tenant_id=task.tenant_id,
            mission_id=task.mission_id,
            task_graph_reference={"execution_task_id": str(task.id), "action": action_name},
            reviewed_success_criteria=[
                {
                    "criteria": "high-risk GTM action completed with evidence and guardian approval",
                    "action": action_name,
                }
            ],
            evidence_references=[{"evidence_id": eid} for eid in evidence_ids],
            review_status="draft",
            review_decision="inconclusive",
            reviewer_type="system",
            reviewer_source=approved_by,
            review_summary=f"Auto-generated draft from completion of high-risk GTM action {action_name}. Reason: {reason}",
            structured_findings=[],
            confidence=None,
            trust_signal={
                "source": "worker_runtime_completion_bridge",
                "side_effect_authorization": auth,
            },
            unresolved_gaps=[],
            recommended_next_actions=[{"action": "human_review", "reason": "high-risk external side effect"}],
            human_approval_required=True,
            human_approval_status="pending",
        )
        repo.add(review)
    except Exception:
        # Best effort bridge; do not fail completion. Logged via audit elsewhere if needed.
        pass

