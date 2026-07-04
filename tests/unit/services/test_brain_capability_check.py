from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.services.brain_capability_check import build_brain_capability_report


@patch("backend.services.brain_capability_check.ProviderRuntimeCredentialRepository")
@patch("backend.services.brain_capability_check.BusinessProfileRepository")
def test_brain_capability_report_ready_with_profile(mock_profile_repo: MagicMock, mock_cred_repo: MagicMock) -> None:
    profile = MagicMock()
    profile.approved_facts = {
        "business_name": {"value": "Ajenda AI"},
        "products_services": {"items": ["Governed runtime"]},
    }
    mock_profile_repo.return_value.get_active_profile_for_tenant.return_value = profile
    mock_cred_repo.return_value.list_for_tenant.return_value = []

    report = build_brain_capability_report(session=MagicMock(), tenant_id="tenant-1")
    payload = report.to_api()

    assert payload["profile_ready"] is True
    assert payload["summary"]["total"] == 12
    assert payload["summary"]["ready"] >= 7
    assert any(item["mission_id"] == "M9" and item["status"] == "READY" for item in payload["missions"])


@patch("backend.services.brain_capability_check.ProviderRuntimeCredentialRepository")
@patch("backend.services.brain_capability_check.BusinessProfileRepository")
def test_brain_capability_report_needs_profile_for_memory_missions(
    mock_profile_repo: MagicMock,
    mock_cred_repo: MagicMock,
) -> None:
    mock_profile_repo.return_value.get_active_profile_for_tenant.return_value = None
    mock_cred_repo.return_value.list_for_tenant.return_value = []

    report = build_brain_capability_report(session=MagicMock(), tenant_id="tenant-1")
    payload = report.to_api()

    assert payload["profile_ready"] is False
    memory_missions = [item for item in payload["missions"] if item["mission_id"] in {"M1", "M2", "M3"}]
    assert all(item["status"] == "NEEDS_PROFILE" for item in memory_missions)
