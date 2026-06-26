"""Ajenda plugin contracts and discovery registry.

External CRM, email, and social providers are optional plugins around the
central Ajenda brain. Standalone mode uses durable tenant records, local
intelligence, and governed HTTP egress without any external plugin.
"""

from backend.services.plugins.registry import (
    PluginDescriptor,
    get_plugin,
    list_plugins,
)

__all__ = [
    "PluginDescriptor",
    "get_plugin",
    "list_plugins",
]
