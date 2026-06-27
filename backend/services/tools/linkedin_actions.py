"""LinkedIn read-only actions via governed external_read_provider credentials."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field

from backend.services.network_egress import get_default_network_egress_authority
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.provider_read_actions import PROVIDER_EXTERNAL_READ_PROVIDER
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    EvidenceItem,
    RuntimeCredentialMaterial,
    SideEffectClass,
    ToolInvocation,
)

LINKEDIN_PROFILE_READ_ACTION = "linkedin.profile_read"
LINKEDIN_API_HOST = "api.linkedin.com"
LINKEDIN_RESTLI_PROTOCOL_VERSION = "2.0.0"
LINKEDIN_API_VERSION = "202405"


class LinkedInProfileReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str | None = Field(default=None, max_length=120)
    fields: tuple[str, ...] = Field(default=("id", "firstName", "lastName", "headline"), max_length=12)


def _credential_secret(material: RuntimeCredentialMaterial | dict[str, Any] | None) -> str | None:
    if material is None:
        return None
    if isinstance(material, dict):
        secret = material.get("secret_value")
        return str(secret) if isinstance(secret, str) and secret else None
    return material.secret_value


def _get_runtime_credential(
    ctx: ActionRuntimeContext,
    *,
    action: str,
    aliases: tuple[str, ...] = (),
) -> RuntimeCredentialMaterial | dict[str, Any] | None:
    for key in (action, *aliases):
        if key in ctx.runtime_credentials:
            return ctx.runtime_credentials[key]
    return None


def _trusted_hosts(material: RuntimeCredentialMaterial | dict[str, Any] | None) -> tuple[str, ...]:
    if material is None:
        return (LINKEDIN_API_HOST,)
    if isinstance(material, dict):
        raw_hosts = material.get("trusted_destination_hosts")
        if raw_hosts:
            return tuple(str(host) for host in raw_hosts)
        return (LINKEDIN_API_HOST,)
    if material.trusted_destination_hosts:
        return material.trusted_destination_hosts
    return (LINKEDIN_API_HOST,)


def _profile_url(*, profile_id: str | None, fields: tuple[str, ...]) -> str:
    projection = ",".join(fields)
    if profile_id and profile_id.strip():
        encoded_id = quote(profile_id.strip(), safe="")
        return (
            f"https://{LINKEDIN_API_HOST}/v2/people/(id:{encoded_id})"
            f"?projection=({projection})"
        )
    return f"https://{LINKEDIN_API_HOST}/v2/me?projection=({projection})"


def _simulated_profile() -> dict[str, Any]:
    return {
        "id": "sim-linkedin-1",
        "firstName": {"localized": {"en_US": "Alex"}},
        "lastName": {"localized": {"en_US": "Lead"}},
        "headline": {"localized": {"en_US": "Simulated LinkedIn profile"}},
    }


def linkedin_profile_read(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = LinkedInProfileReadInput.model_validate(invocation.input)
    credential = _get_runtime_credential(
        context,
        action=invocation.action,
        aliases=(LINKEDIN_PROFILE_READ_ACTION, "provider.external_read", PROVIDER_EXTERNAL_READ_PROVIDER),
    )
    secret = _credential_secret(credential)
    profile: dict[str, Any]
    real = False
    status_code: int | None = None

    if secret:
        url = _profile_url(profile_id=payload.profile_id, fields=payload.fields)
        headers = {
            "Authorization": f"Bearer {secret}",
            "X-Restli-Protocol-Version": LINKEDIN_RESTLI_PROTOCOL_VERSION,
            "LinkedIn-Version": LINKEDIN_API_VERSION,
        }
        try:
            _destination, response = get_default_network_egress_authority().request(
                method="GET",
                url=url,
                headers=headers,
                json_body=None,
                allowed_hosts=list(_trusted_hosts(credential)),
                action_name=LINKEDIN_PROFILE_READ_ACTION,
                timeout_seconds=10.0,
            )
            status_code = response.status_code
            if not 200 <= response.status_code < 300:
                raise ValueError(f"LinkedIn API returned HTTP {response.status_code}")
            profile = json.loads(response.body_text or "{}")
            if not isinstance(profile, dict):
                raise ValueError("LinkedIn API returned non-object profile payload")
            real = True
        except Exception as exc:
            raise ValueError(f"LinkedIn profile read failed on credentialed path: {exc}") from exc
    else:
        profile = _simulated_profile()

    output = {
        "profile": profile,
        "profile_id": payload.profile_id,
        "real": real,
        "source": "linkedin_api" if real else "simulated",
    }
    if status_code is not None:
        output["real_response"] = {"status_code": status_code}

    summary = (
        "LinkedIn profile read completed via API"
        if real
        else "LinkedIn profile read (simulated; no credential)"
    )
    evidence = EvidenceItem(
        evidence_type="action_result",
        evidence_source=f"tool.invoke.{LINKEDIN_PROFILE_READ_ACTION}",
        action_name=LINKEDIN_PROFILE_READ_ACTION,
        tool_provider=PROVIDER_EXTERNAL_READ_PROVIDER,
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload=output,
        records_inspected=[str(profile.get("id", "unknown"))],
        side_effect_class=SideEffectClass.EXTERNAL_READ,
    )
    return ActionResult(
        action=LINKEDIN_PROFILE_READ_ACTION,
        provider=PROVIDER_EXTERNAL_READ_PROVIDER,
        side_effect_class=SideEffectClass.EXTERNAL_READ,
        output=output,
        evidence=[evidence],
        summary=summary,
    )


def register_linkedin_actions(registry: ActionRegistry) -> None:
    registry.register(
        ActionDefinition(
            name=LINKEDIN_PROFILE_READ_ACTION,
            handler=linkedin_profile_read,
            provider=PROVIDER_EXTERNAL_READ_PROVIDER,
            input_model=LinkedInProfileReadInput,
            side_effect_class=SideEffectClass.EXTERNAL_READ,
        )
    )