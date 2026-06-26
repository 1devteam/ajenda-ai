from __future__ import annotations

from backend.services.plugins.registry import get_plugin, list_plugins, plugin_for_action


def test_list_plugins_includes_central_brain() -> None:
    plugins = list_plugins()
    plugin_ids = {plugin.plugin_id for plugin in plugins}
    assert "ajenda-brain" in plugin_ids
    assert "hubspot-crm" in plugin_ids
    assert "smtp-email" in plugin_ids


def test_get_plugin_returns_descriptor() -> None:
    plugin = get_plugin("ajenda-brain")
    assert plugin is not None
    assert plugin.mode == "standalone"
    assert "web.research" in plugin.supported_actions


def test_plugin_for_action_maps_sales_research() -> None:
    plugins = plugin_for_action("sales.research")
    plugin_ids = {plugin.plugin_id for plugin in plugins}
    assert "ajenda-brain" in plugin_ids
    assert "hubspot-crm" in plugin_ids
