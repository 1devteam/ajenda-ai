"""Stable registration facade for GTM actions."""

from __future__ import annotations

from backend.services.credentials.runtime_authority import CredentialRequirement
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.gtm_action_crm import crm_upsert_handler
from backend.services.tools.gtm_action_drafts import email_draft_handler, social_draft_handler
from backend.services.tools.gtm_action_email import email_check_handler, email_send_handler
from backend.services.tools.gtm_action_lead import lead_enrich_handler
from backend.services.tools.gtm_action_social import social_publish_handler
from backend.services.tools.schemas import (
    GtmCrmUpsertInput,
    GtmEmailCheckInput,
    GtmEmailDraftInput,
    GtmEmailSendInput,
    GtmLeadEnrichInput,
    GtmSocialDraftInput,
    GtmSocialPublishInput,
    SideEffectClass,
)
from backend.services.tools.side_effect_resolvers import credential_reference_external_write


def register_gtm_actions(registry: ActionRegistry) -> None:
    registry.register(
        ActionDefinition(
            name="gtm.lead_enrich",
            handler=lead_enrich_handler,
            side_effect_class=SideEffectClass.NONE,
            provider="local_gtm",
            input_model=GtmLeadEnrichInput,
        )
    )
    registry.register(
        ActionDefinition(
            name="gtm.email_draft",
            handler=email_draft_handler,
            side_effect_class=SideEffectClass.NONE,
            provider="local_gtm",
            input_model=GtmEmailDraftInput,
        )
    )
    registry.register(
        ActionDefinition(
            name="gtm.social_draft",
            handler=social_draft_handler,
            side_effect_class=SideEffectClass.NONE,
            provider="local_gtm",
            input_model=GtmSocialDraftInput,
        )
    )
    registry.register(
        ActionDefinition(
            name="gtm.email_send",
            handler=email_send_handler,
            side_effect_class=SideEffectClass.EXTERNAL_SEND,
            provider="external_email",
            input_model=GtmEmailSendInput,
            credential_requirement=CredentialRequirement(
                provider="external_email",
                credential_type="api_key",
                allowed_credential_types=("api_key", "smtp", "platform_master"),
                allowed_side_effect_classes=(SideEffectClass.EXTERNAL_SEND,),
            ),
        )
    )
    registry.register(
        ActionDefinition(
            name="gtm.email_check",
            handler=email_check_handler,
            side_effect_class=SideEffectClass.EXTERNAL_READ,
            provider="external_email",
            input_model=GtmEmailCheckInput,
        )
    )
    registry.register(
        ActionDefinition(
            name="gtm.crm_upsert",
            handler=crm_upsert_handler,
            side_effect_class=SideEffectClass.INTERNAL_WRITE,
            side_effect_resolver=credential_reference_external_write,
            provider="ajenda_brain",
            input_model=GtmCrmUpsertInput,
        )
    )
    registry.register(
        ActionDefinition(
            name="gtm.social_publish",
            handler=social_publish_handler,
            side_effect_class=SideEffectClass.EXTERNAL_PUBLISH,
            provider="external_social",
            input_model=GtmSocialPublishInput,
            credential_requirement=CredentialRequirement(
                provider="external_social",
                credential_type="api_key",
                allowed_side_effect_classes=(SideEffectClass.EXTERNAL_PUBLISH,),
            ),
        )
    )
