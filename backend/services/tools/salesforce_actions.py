"""Salesforce read-only SOQL query action via governed external_read_provider credentials."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

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

SALESFORCE_SOQL_READ_ACTION = "salesforce.soql_read"
_SOQL_SELECT_PATTERN = re.compile(r"^\s*select\b", re.IGNORECASE)
_FORBIDDEN_SOQL_PATTERN = re.compile(
    r"\b(insert|update|delete|upsert|merge|undelete)\b",
    re.IGNORECASE,
)


class SalesforceSoqlReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    soql: str = Field(min_length=1, max_length=4000)
    api_version: str = Field(default="v59.0", min_length=4, max_length=16)

    @field_validator("soql")
    @classmethod
    def validate_read_only_soql(cls, value: str) -> str:
        normalized = value.strip()
        if not _SOQL_SELECT_PATTERN.match(normalized):
            raise ValueError("salesforce.soql_read only supports read-only SELECT queries")
        if _FORBIDDEN_SOQL_PATTERN.search(normalized):
            raise ValueError("salesforce.soql_read rejects mutating SOQL keywords")
        return normalized

    @field_validator("api_version")
    @classmethod
    def validate_api_version(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith("v") or not normalized[1:].replace(".", "").isdigit():
            raise ValueError("api_version must look like v59.0")
        return normalized


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
        return ()
    if isinstance(material, dict):
        raw_hosts = material.get("trusted_destination_hosts")
        if raw_hosts:
            return tuple(str(host) for host in raw_hosts)
        return ()
    return material.trusted_destination_hosts or ()


def _simulated_query_result() -> dict[str, Any]:
    return {
        "totalSize": 1,
        "done": True,
        "records": [
            {
                "attributes": {"type": "Account", "url": "/services/data/v59.0/sobjects/Account/sim-1"},
                "Id": "sim-sf-1",
                "Name": "Simulated Salesforce Account",
            }
        ],
    }


def salesforce_soql_read(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = SalesforceSoqlReadInput.model_validate(invocation.input)
    credential = _get_runtime_credential(
        context,
        action=invocation.action,
        aliases=(SALESFORCE_SOQL_READ_ACTION, "provider.external_read", PROVIDER_EXTERNAL_READ_PROVIDER),
    )
    secret = _credential_secret(credential)
    result_payload: dict[str, Any]
    real = False
    status_code: int | None = None

    if secret:
        trusted_hosts = _trusted_hosts(credential)
        if not trusted_hosts:
            raise ValueError("salesforce.soql_read credential missing trusted_destination_hosts")
        host = trusted_hosts[0].strip().lower().rstrip(".")
        query_url = (
            f"https://{host}/services/data/{payload.api_version}/query"
            f"?q={quote(payload.soql, safe='')}"
        )
        headers = {"Authorization": f"Bearer {secret}"}
        try:
            _destination, response = get_default_network_egress_authority().request(
                method="GET",
                url=query_url,
                headers=headers,
                json_body=None,
                allowed_hosts=[host],
                action_name=SALESFORCE_SOQL_READ_ACTION,
                timeout_seconds=15.0,
            )
            status_code = response.status_code
            if not 200 <= response.status_code < 300:
                raise ValueError(f"Salesforce API returned HTTP {response.status_code}")
            parsed = json.loads(response.body_text or "{}")
            if not isinstance(parsed, dict):
                raise ValueError("Salesforce API returned non-object query payload")
            result_payload = parsed
            real = True
        except Exception as exc:
            raise ValueError(f"Salesforce SOQL read failed on credentialed path: {exc}") from exc
    else:
        result_payload = _simulated_query_result()

    output = {
        "soql": payload.soql,
        "api_version": payload.api_version,
        "result": result_payload,
        "real": real,
        "source": "salesforce_api" if real else "simulated",
    }
    if status_code is not None:
        output["real_response"] = {"status_code": status_code}

    record_count = int(result_payload.get("totalSize", len(result_payload.get("records", []))))
    summary = (
        f"Salesforce SOQL read returned {record_count} record(s) via API"
        if real
        else "Salesforce SOQL read (simulated; no credential)"
    )
    evidence = EvidenceItem(
        evidence_type="action_result",
        evidence_source=f"tool.invoke.{SALESFORCE_SOQL_READ_ACTION}",
        action_name=SALESFORCE_SOQL_READ_ACTION,
        tool_provider=PROVIDER_EXTERNAL_READ_PROVIDER,
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload=output,
        records_inspected=[str(item.get("Id", "")) for item in result_payload.get("records", []) if isinstance(item, dict)],
        side_effect_class=SideEffectClass.EXTERNAL_READ,
    )
    return ActionResult(
        action=SALESFORCE_SOQL_READ_ACTION,
        provider=PROVIDER_EXTERNAL_READ_PROVIDER,
        side_effect_class=SideEffectClass.EXTERNAL_READ,
        output=output,
        evidence=[evidence],
        summary=summary,
    )


def register_salesforce_actions(registry: ActionRegistry) -> None:
    registry.register(
        ActionDefinition(
            name=SALESFORCE_SOQL_READ_ACTION,
            handler=salesforce_soql_read,
            provider=PROVIDER_EXTERNAL_READ_PROVIDER,
            input_model=SalesforceSoqlReadInput,
            side_effect_class=SideEffectClass.EXTERNAL_READ,
        )
    )