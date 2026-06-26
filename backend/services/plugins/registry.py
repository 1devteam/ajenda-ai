from __future__ import annotations

from dataclasses import dataclass

from backend.services.plugins.contracts import BUILTIN_PLUGIN_CONTRACTS, PluginContract, PluginMode


@dataclass(frozen=True, slots=True)
class PluginDescriptor:
    plugin_id: str
    display_name: str
    category: str
    provider: str
    mode: PluginMode
    description: str
    credential_provider: str | None
    credential_types: tuple[str, ...]
    integration_types: tuple[str, ...]
    trusted_hosts: tuple[str, ...]
    crm_search_path: str | None
    crm_upsert_path: str | None
    supported_actions: tuple[str, ...]
    standalone_actions: tuple[str, ...]
    requires_external_credential: bool
    documentation_ref: str | None


def _to_descriptor(contract: PluginContract) -> PluginDescriptor:
    return PluginDescriptor(
        plugin_id=contract.plugin_id,
        display_name=contract.display_name,
        category=contract.category,
        provider=contract.provider,
        mode=contract.mode,
        description=contract.description,
        credential_provider=contract.credential_provider,
        credential_types=contract.credential_types,
        integration_types=contract.integration_types,
        trusted_hosts=contract.trusted_hosts,
        crm_search_path=contract.crm_paths.search_path if contract.crm_paths else None,
        crm_upsert_path=contract.crm_paths.upsert_path if contract.crm_paths else None,
        supported_actions=contract.supported_actions,
        standalone_actions=contract.standalone_actions,
        requires_external_credential=contract.requires_external_credential,
        documentation_ref=contract.documentation_ref,
    )


_PLUGIN_INDEX: dict[str, PluginDescriptor] = {
    contract.plugin_id: _to_descriptor(contract) for contract in BUILTIN_PLUGIN_CONTRACTS
}


def list_plugins(*, category: str | None = None, mode: PluginMode | None = None) -> list[PluginDescriptor]:
    plugins = list(_PLUGIN_INDEX.values())
    if category is not None:
        normalized = category.strip().lower()
        plugins = [plugin for plugin in plugins if plugin.category == normalized]
    if mode is not None:
        plugins = [plugin for plugin in plugins if plugin.mode == mode]
    return sorted(plugins, key=lambda item: (item.category, item.plugin_id))


def get_plugin(plugin_id: str) -> PluginDescriptor | None:
    normalized = plugin_id.strip().lower()
    return _PLUGIN_INDEX.get(normalized)


def plugin_for_action(action_name: str) -> list[PluginDescriptor]:
    normalized = action_name.strip()
    return [
        plugin
        for plugin in _PLUGIN_INDEX.values()
        if normalized in plugin.supported_actions or normalized in plugin.standalone_actions
    ]
