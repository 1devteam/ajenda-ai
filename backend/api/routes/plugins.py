from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict

from backend.services.plugins.registry import PluginDescriptor, get_plugin, list_plugins, plugin_for_action

router = APIRouter(prefix="/plugins", tags=["plugins"])


class PluginContractResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plugin_id: str
    display_name: str
    category: str
    provider: str
    mode: Literal["standalone", "plugin", "hybrid"]
    description: str
    credential_provider: str | None
    credential_types: list[str]
    integration_types: list[str]
    trusted_hosts: list[str]
    crm_search_path: str | None
    crm_upsert_path: str | None
    supported_actions: list[str]
    standalone_actions: list[str]
    requires_external_credential: bool
    documentation_ref: str | None


class PluginListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plugins: list[PluginContractResponse]
    central_brain_plugin_id: str = "ajenda-brain"


def _to_response(descriptor: PluginDescriptor) -> PluginContractResponse:
    return PluginContractResponse(
        plugin_id=descriptor.plugin_id,
        display_name=descriptor.display_name,
        category=descriptor.category,
        provider=descriptor.provider,
        mode=descriptor.mode,
        description=descriptor.description,
        credential_provider=descriptor.credential_provider,
        credential_types=list(descriptor.credential_types),
        integration_types=list(descriptor.integration_types),
        trusted_hosts=list(descriptor.trusted_hosts),
        crm_search_path=descriptor.crm_search_path,
        crm_upsert_path=descriptor.crm_upsert_path,
        supported_actions=list(descriptor.supported_actions),
        standalone_actions=list(descriptor.standalone_actions),
        requires_external_credential=descriptor.requires_external_credential,
        documentation_ref=descriptor.documentation_ref,
    )


@router.get("", response_model=PluginListResponse)
def list_available_plugins(
    category: str | None = None,
    mode: Literal["standalone", "plugin", "hybrid"] | None = None,
) -> PluginListResponse:
    plugins = list_plugins(category=category, mode=mode)
    return PluginListResponse(plugins=[_to_response(plugin) for plugin in plugins])


@router.get("/{plugin_id}", response_model=PluginContractResponse)
def get_available_plugin(plugin_id: str) -> PluginContractResponse:
    plugin = get_plugin(plugin_id)
    if plugin is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="plugin not found")
    return _to_response(plugin)


@router.get("/actions/{action_name}/plugins", response_model=PluginListResponse)
def list_plugins_for_action(action_name: str) -> PluginListResponse:
    plugins = plugin_for_action(action_name)
    return PluginListResponse(plugins=[_to_response(plugin) for plugin in plugins])
