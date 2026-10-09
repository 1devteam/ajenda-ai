"""Stable registration facade for sales and record actions."""

from __future__ import annotations

from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.sales_action_followup import (
    sales_create_followup_task,
    sales_draft_followup,
    sales_log_activity,
)
from backend.services.tools.sales_action_qualification import (
    sales_qualify,
    sales_recommend_next_action,
    sales_score_lead,
)
from backend.services.tools.sales_action_records import record_read, record_search, record_write
from backend.services.tools.sales_action_research import sales_research
from backend.services.tools.schemas import (
    FollowupDraftInput,
    RecordReadInput,
    RecordSearchInput,
    RecordWriteInput,
    SalesLeadInput,
    SideEffectClass,
)
from backend.services.tools.side_effect_resolvers import credential_reference_external_read


def register_sales_actions(registry: ActionRegistry) -> None:
    registry.register(
        ActionDefinition(
            name="record.search", handler=record_search, provider="local_records", input_model=RecordSearchInput
        )
    )
    registry.register(
        ActionDefinition(name="record.read", handler=record_read, provider="local_records", input_model=RecordReadInput)
    )
    registry.register(
        ActionDefinition(
            name="record.write",
            handler=record_write,
            provider="local_records",
            input_model=RecordWriteInput,
            side_effect_class=SideEffectClass.INTERNAL_WRITE,
        )
    )
    registry.register(
        ActionDefinition(
            name="sales.research",
            handler=sales_research,
            provider="ajenda_brain",
            input_model=SalesLeadInput,
            side_effect_class=SideEffectClass.INTERNAL_READ,
            side_effect_resolver=credential_reference_external_read,
            aliases=("crm.research", "crm.read"),
        )
    )
    registry.register(
        ActionDefinition(
            name="sales.qualify", handler=sales_qualify, provider="local_sales", input_model=SalesLeadInput
        )
    )
    registry.register(
        ActionDefinition(
            name="sales.score_lead", handler=sales_score_lead, provider="local_sales", input_model=SalesLeadInput
        )
    )
    registry.register(
        ActionDefinition(
            name="sales.recommend_next_action",
            handler=sales_recommend_next_action,
            provider="local_sales",
            input_model=SalesLeadInput,
        )
    )
    registry.register(
        ActionDefinition(
            name="sales.draft_followup",
            handler=sales_draft_followup,
            provider="local_sales",
            input_model=FollowupDraftInput,
            aliases=("gtm.message_draft",),
        )
    )
    registry.register(
        ActionDefinition(
            name="sales.log_activity",
            handler=sales_log_activity,
            provider="local_sales",
            input_model=RecordWriteInput,
            side_effect_class=SideEffectClass.INTERNAL_WRITE,
        )
    )
    registry.register(
        ActionDefinition(
            name="sales.create_followup_task",
            handler=sales_create_followup_task,
            provider="local_sales",
            input_model=RecordWriteInput,
            side_effect_class=SideEffectClass.INTERNAL_WRITE,
        )
    )
