"""Governed public internet actions: page read, browser session, open write."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from backend.services.internet import InternetAccessMode, fetch_public_page
from backend.services.internet.browser_session import browser_session_as_dict, run_browser_session
from backend.services.internet.open_write import execute_open_write
from backend.services.ontology.evidence_lineage import (
    EvidenceLineage,
    EvidenceLineageResolution,
    EvidenceOriginType,
    EvidenceSourceIdentity,
)
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.web_action_io import web_browser_session, web_open_write, web_page_read
from backend.services.tools.web_action_contacts import research_observe_contacts
from backend.services.tools.web_action_identity import research_verify_public_identity
from backend.services.tools.contact_observation import (
    extract_observed_contacts,
    page_host,
    prospect_source_url,
)
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    EvidenceItem,
    ResearchObserveContactsInput,
    ResearchVerifyPublicIdentityInput,
    SideEffectClass,
    ToolInvocation,
    WebBrowserSessionInput,
    WebOpenWriteInput,
    WebPageReadInput,
)















def register_web_actions(registry: ActionRegistry) -> None:
    registry.register(
        ActionDefinition(
            name="web.page_read",
            handler=web_page_read,
            provider="ajenda_internet",
            input_model=WebPageReadInput,
            side_effect_class=SideEffectClass.EXTERNAL_READ,
        )
    )
    registry.register(
        ActionDefinition(
            name="research.observe_contacts",
            handler=research_observe_contacts,
            provider="ajenda_internet",
            input_model=ResearchObserveContactsInput,
            side_effect_class=SideEffectClass.EXTERNAL_READ,
        )
    )
    registry.register(
        ActionDefinition(
            name="research.verify_public_identity",
            handler=research_verify_public_identity,
            provider="ajenda_internet",
            input_model=ResearchVerifyPublicIdentityInput,
            side_effect_class=SideEffectClass.EXTERNAL_READ,
        )
    )
    registry.register(
        ActionDefinition(
            name="web.browser_session",
            handler=web_browser_session,
            provider="ajenda_internet",
            input_model=WebBrowserSessionInput,
            side_effect_class=SideEffectClass.EXTERNAL_READ,
        )
    )
    registry.register(
        ActionDefinition(
            name="web.open_write",
            handler=web_open_write,
            provider="ajenda_internet",
            input_model=WebOpenWriteInput,
            side_effect_class=SideEffectClass.EXTERNAL_WRITE,
        )
    )
