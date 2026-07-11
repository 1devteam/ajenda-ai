"""Vertical operations package (ADR-0007).

Phase B: runtime-bound templates (research/email/social) materialize planned
ExecutionTask rows and may queue via ExecutionCoordinator.

Phase C: plan-only high-risk templates (ads/code/finance). Catalog/plan only;
runtime queue fails closed until providers prove safe.

No parallel execution coordinator, Celery loop, or agent swarm runtime.
"""

from backend.services.vertical_ops.plan_templates import (
    KNOWN_TEMPLATE_IDS,
    PHASE_B_TEMPLATE_IDS,
    PHASE_C_TEMPLATE_IDS,
    VERTICAL_MISSION_TEMPLATES,
    VERTICAL_MISSION_TEMPLATES_BY_ID,
    VerticalMissionTemplate,
    VerticalTemplateStep,
    get_vertical_mission_template,
    list_vertical_mission_templates,
)
from backend.services.vertical_ops.template_service import (
    PlannedVerticalTaskSpec,
    VerticalOpsTemplateService,
    VerticalTemplateApplyResult,
    VerticalTemplateBundle,
    VerticalTemplateQueueResult,
)

__all__ = [
    "KNOWN_TEMPLATE_IDS",
    "PHASE_B_TEMPLATE_IDS",
    "PHASE_C_TEMPLATE_IDS",
    "VERTICAL_MISSION_TEMPLATES",
    "VERTICAL_MISSION_TEMPLATES_BY_ID",
    "PlannedVerticalTaskSpec",
    "VerticalMissionTemplate",
    "VerticalOpsTemplateService",
    "VerticalTemplateApplyResult",
    "VerticalTemplateBundle",
    "VerticalTemplateQueueResult",
    "VerticalTemplateStep",
    "get_vertical_mission_template",
    "list_vertical_mission_templates",
]
