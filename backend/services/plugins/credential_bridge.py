from __future__ import annotations

BRAIN_ACTION_PLUGIN_CREDENTIALS: dict[str, tuple[str, ...]] = {
    "sales.research": ("external_crm",),
    "crm.research": ("external_crm",),
    "crm.read": ("external_crm",),
    "gtm.crm_upsert": ("external_crm",),
}


def accepts_plugin_credential(*, action_name: str, action_provider: str, credential_provider: str) -> bool:
    if action_provider != "ajenda_brain":
        return False
    allowed = BRAIN_ACTION_PLUGIN_CREDENTIALS.get(action_name, ())
    return credential_provider in allowed
