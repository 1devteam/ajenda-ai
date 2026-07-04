from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.services.brain_capability_check import build_brain_capability_report


@patch("backend.services.brain_capability_check.get_settings")
@patch("backend.services.brain_capability_check.ProviderRuntimeCredentialRepository")
@patch("backend.services.brain_capability_check.BusinessProfileRepository")
def test_m11_blocked_when_email_send_in_never_do(
    mock_profile_repo: MagicMock,
    mock_cred_repo: MagicMock,
    mock_settings: MagicMock,
) -> None:
    mock_settings.return_value.llm_ready = True
    profile = MagicMock()
    profile.approved_facts = {}
    mock_profile_repo.return_value.get_active_profile_for_tenant.return_value = profile
    mock_cred_repo.return_value.list_for_tenant.return_value = [
        MagicMock(
            revoked=False,
            enabled=True,
            allowed_actions=["gtm.email_send"],
        )
    ]

    report = build_brain_capability_report(session=MagicMock(), tenant_id="tenant-1")
    m11 = next(item for item in report.missions if item.mission_id == "M11")
    assert m11.status == "BLOCKED"


@patch("backend.services.brain_capability_check.get_settings")
@patch("backend.services.brain_capability_check.ProviderRuntimeCredentialRepository")
@patch("backend.services.brain_capability_check.BusinessProfileRepository")
def test_m11_ready_when_charter_allows_and_email_configured(
    mock_profile_repo: MagicMock,
    mock_cred_repo: MagicMock,
    mock_settings: MagicMock,
) -> None:
    mock_settings.return_value.llm_ready = True
    profile = MagicMock()
    profile.approved_facts = {
        "operating_charter": {
            "value": {
                "schema_version": 1,
                "may_prepare": ["gtm.email_draft"],
                "may_perform": ["gtm.email_send", "gtm.crm_upsert"],
                "never_do": ["gtm.social_publish"],
                "approval_mode": "notify_before_external",
            }
        }
    }
    mock_profile_repo.return_value.get_active_profile_for_tenant.return_value = profile
    mock_cred_repo.return_value.list_for_tenant.return_value = [
        MagicMock(
            revoked=False,
            enabled=True,
            allowed_actions=["gtm.email_send"],
        )
    ]

    report = build_brain_capability_report(session=MagicMock(), tenant_id="tenant-1")
    m11 = next(item for item in report.missions if item.mission_id == "M11")
    assert m11.status == "READY"
