"""Stable registration facade for governed public-internet actions."""

from __future__ import annotations

from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.schemas import (
    ResearchObserveContactsInput,
    ResearchVerifyPublicIdentityInput,
    SideEffectClass,
    WebBrowserSessionInput,
    WebOpenWriteInput,
    WebPageReadInput,
)
from backend.services.tools.web_action_contacts import research_observe_contacts
from backend.services.tools.web_action_identity import research_verify_public_identity
from backend.services.tools.web_action_io import web_browser_session, web_open_write, web_page_read


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
