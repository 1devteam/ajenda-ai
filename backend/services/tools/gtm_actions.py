"""GTM actions for lead enrichment and email drafting (PR6 expansion).

Core actions implemented with evidence, side-effect classification, and credential requirements for high-risk external.
Local/simulated providers for proof-of-concept and CI; production uses credential injection + egress authority.
"""

from __future__ import annotations

import base64
import hashlib
import json
from email.mime.text import MIMEText
from typing import Any
from urllib.parse import quote

from backend.services.credentials.runtime_authority import CredentialRequirement
from backend.services.document_artifacts import read_artifact, update_review_status
from backend.services.draft_generation import generate_and_persist_draft
from backend.services.network_egress import get_default_network_egress_authority
from backend.services.plugins.crm_client import default_crm_client
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.gtm_action_crm import crm_upsert_handler
from backend.services.tools.gtm_action_drafts import email_draft_handler, social_draft_handler
from backend.services.tools.gtm_action_email import email_check_handler, email_send_handler
from backend.services.tools.gtm_action_lead import lead_enrich_handler
from backend.services.tools.gtm_action_social import social_publish_handler
from backend.services.tools.email_send_idempotency import (
    claim_smtp_send,
    complete_smtp_send,
    release_smtp_send,
)
from backend.services.tools.email_transport import (
    credential_transport_mode,
    parse_smtp_secret,
    send_via_smtp,
)
from backend.services.tools.external_sim_policy import allow_simulated_external
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    EvidenceItem,
    GtmCrmUpsertInput,
    GtmEmailCheckInput,
    GtmEmailDraftInput,
    GtmEmailSendInput,
    GtmLeadEnrichInput,
    GtmSocialDraftInput,
    GtmSocialPublishInput,
    RuntimeCredentialMaterial,
    SideEffectClass,
    ToolInvocation,
)
from backend.services.tools.side_effect_resolvers import credential_reference_external_write













def register_gtm_actions(registry: ActionRegistry) -> None:



    ) -> tuple[str, str, str, str | None]:
        artifact_id = inp.artifact_id or str(inp.context.get("artifact_id", "") or "").strip() or None
        to = inp.to
        subject = inp.subject or str(inp.context.get("subject", "") or "")
        body_text = inp.body or str(inp.context.get("body", "") or "")

        if artifact_id and ctx.session_factory is not None:
            session = ctx.session_factory()
            try:
                artifact = read_artifact(session, tenant_id=ctx.tenant_id, artifact_id=artifact_id)
            finally:
                session.close()
            if artifact is not None:
                content = artifact.get("content")
                if isinstance(content, dict):
                    body_text = str(content.get("body") or content.get("draft") or body_text)
                    subject = str(content.get("subject") or subject)
                    to = str(content.get("to") or to)
                review_status = str(artifact.get("review_status") or "")
                if review_status not in {"approved", "sent"}:
                    raise ValueError(f"artifact {artifact_id} is not approved for send (status={review_status})")
        if not subject.strip():
            raise ValueError("subject is required for gtm.email_send")
        if not body_text.strip():
            raise ValueError("body is required for gtm.email_send")
        return to, subject.strip(), body_text.strip(), artifact_id




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
                # Gmail API bearer (api_key) or SMTP JSON (smtp / platform_master email master).
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
