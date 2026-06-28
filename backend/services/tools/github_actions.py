"""GitHub read-only actions via governed external_read_provider credentials."""

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

GITHUB_REPO_READ_ACTION = "github.repo_read"
GITHUB_API_HOST = "api.github.com"
GITHUB_API_VERSION = "2022-11-28"


class GitHubRepoReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner: str = Field(min_length=1, max_length=120)
    repo: str = Field(min_length=1, max_length=160)


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
        return (GITHUB_API_HOST,)
    if isinstance(material, dict):
        raw_hosts = material.get("trusted_destination_hosts")
        if raw_hosts:
            return tuple(str(host) for host in raw_hosts)
        return (GITHUB_API_HOST,)
    if material.trusted_destination_hosts:
        return material.trusted_destination_hosts
    return (GITHUB_API_HOST,)


def _repo_url(*, owner: str, repo: str) -> str:
    encoded_owner = quote(owner.strip(), safe="")
    encoded_repo = quote(repo.strip(), safe="")
    return f"https://{GITHUB_API_HOST}/repos/{encoded_owner}/{encoded_repo}"


def _github_headers(secret: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {secret}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }


def _simulated_repo(*, owner: str, repo: str) -> dict[str, Any]:
    return {
        "id": 1,
        "full_name": f"{owner}/{repo}",
        "name": repo,
        "owner": {"login": owner},
        "private": False,
        "description": "Simulated GitHub repository metadata",
    }


def github_repo_read(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = GitHubRepoReadInput.model_validate(invocation.input)
    credential = _get_runtime_credential(
        context,
        action=invocation.action,
        aliases=(GITHUB_REPO_READ_ACTION, "provider.external_read", PROVIDER_EXTERNAL_READ_PROVIDER),
    )
    secret = _credential_secret(credential)
    repository: dict[str, Any]
    real = False
    status_code: int | None = None

    if secret:
        url = _repo_url(owner=payload.owner, repo=payload.repo)
        try:
            _destination, response = get_default_network_egress_authority().request(
                method="GET",
                url=url,
                headers=_github_headers(secret),
                json_body=None,
                allowed_hosts=list(_trusted_hosts(credential)),
                action_name=GITHUB_REPO_READ_ACTION,
                timeout_seconds=15.0,
            )
            status_code = response.status_code
            if not 200 <= response.status_code < 300:
                raise ValueError(f"GitHub API returned HTTP {response.status_code}")
            parsed = json.loads(response.body_text or "{}")
            if not isinstance(parsed, dict):
                raise ValueError("GitHub API returned non-object repository payload")
            repository = parsed
            real = True
        except Exception as exc:
            raise ValueError(f"GitHub repository read failed on credentialed path: {exc}") from exc
    else:
        repository = _simulated_repo(owner=payload.owner, repo=payload.repo)

    output = {
        "owner": payload.owner,
        "repo": payload.repo,
        "repository": repository,
        "real": real,
        "source": "github_api" if real else "simulated",
    }
    if status_code is not None:
        output["real_response"] = {"status_code": status_code}

    summary = (
        f"Read GitHub repository {payload.owner}/{payload.repo} via API"
        if real
        else f"Read simulated GitHub repository {payload.owner}/{payload.repo}; no credential"
    )
    evidence = EvidenceItem(
        evidence_type="action_result",
        evidence_source=f"tool.invoke.{GITHUB_REPO_READ_ACTION}",
        action_name=GITHUB_REPO_READ_ACTION,
        tool_provider=PROVIDER_EXTERNAL_READ_PROVIDER,
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload=output,
        records_inspected=[str(repository.get("full_name", f"{payload.owner}/{payload.repo}"))],
        side_effect_class=SideEffectClass.EXTERNAL_READ,
    )
    return ActionResult(
        action=GITHUB_REPO_READ_ACTION,
        provider=PROVIDER_EXTERNAL_READ_PROVIDER,
        side_effect_class=SideEffectClass.EXTERNAL_READ,
        output=output,
        evidence=[evidence],
        summary=summary,
    )


def register_github_actions(registry: ActionRegistry) -> None:
    registry.register(
        ActionDefinition(
            name=GITHUB_REPO_READ_ACTION,
            handler=github_repo_read,
            provider=PROVIDER_EXTERNAL_READ_PROVIDER,
            input_model=GitHubRepoReadInput,
            side_effect_class=SideEffectClass.EXTERNAL_READ,
        )
    )