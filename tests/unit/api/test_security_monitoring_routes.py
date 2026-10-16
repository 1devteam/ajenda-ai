from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from backend.api.routes import observability


def test_security_history_filters_operational_findings_and_preserves_unassessed(monkeypatch) -> None:
    mission_id = uuid4()
    tenant_id = uuid4()
    snapshot = SimpleNamespace(
        id=uuid4(),
        mission_id=mission_id,
        runtime_summary={"security_status": "alert"},
        findings=[
            {"category": "security_lease_integrity", "code": "lease-mismatch", "severity": "error"},
            {"category": "semantic_drift", "code": "not-an-attack", "severity": "warning"},
        ],
        observed_at=datetime.now(UTC),
    )
    repository = SimpleNamespace(list_for_tenant=lambda **_: [snapshot])
    monkeypatch.setattr(observability, "AssuranceSnapshotRepository", lambda _: repository)
    permission_check = MagicMock()
    monkeypatch.setattr(observability, "require_route_permission", permission_check)
    history = observability.security_monitoring_history(request=object(), tenant_id=tenant_id, session=MagicMock())
    assert len(history) == 1
    assert history[0].security_status == "alert"
    assert [item["category"] for item in history[0].security_findings] == ["security_lease_integrity"]
    assert history[0].grants_execution_authority is False
    permission_check.assert_called_once()


def test_security_summary_does_not_treat_legacy_as_cleared(monkeypatch) -> None:
    tenant_id = uuid4()

    def row(status):
        return SimpleNamespace(
            mission_id=uuid4(),
            runtime_summary={} if status is None else {"security_status": status},
        )

    repository = SimpleNamespace(list_for_tenant=lambda **_: [row("alert"), row("no_findings_observed"), row(None)])
    monkeypatch.setattr(observability, "AssuranceSnapshotRepository", lambda _: repository)
    monkeypatch.setattr(observability, "require_route_permission", lambda **_: None)
    summary = observability.security_monitoring_summary(request=object(), tenant_id=tenant_id, session=MagicMock())
    assert summary.observed_mission_count == 3
    assert summary.alert_count == 1
    assert summary.no_findings_observed_count == 1
    assert summary.unassessed_count == 1
    assert summary.full_tenant_clearance is False
