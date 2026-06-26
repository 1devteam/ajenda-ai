from __future__ import annotations

from backend.services.plugins.credential_bridge import accepts_plugin_credential


def test_brain_action_accepts_external_crm_plugin_credential() -> None:
    assert accepts_plugin_credential(
        action_name="sales.research",
        action_provider="ajenda_brain",
        credential_provider="external_crm",
    )


def test_non_brain_action_rejects_plugin_bridge() -> None:
    assert not accepts_plugin_credential(
        action_name="gtm.email_send",
        action_provider="external_email",
        credential_provider="external_crm",
    )
