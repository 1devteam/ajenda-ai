"""Unit tests for TenantLifecycleService.provision(source=...)."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from backend.domain.provision_source import ProvisionSource
from backend.services.tenant_lifecycle import TenantLifecycleService


def _make_service() -> tuple[TenantLifecycleService, MagicMock, MagicMock]:
    session = MagicMock()
    svc = TenantLifecycleService(session)
    repo = MagicMock()
    svc._tenants = repo
    return svc, repo, session


def _tenant(*, slug: str = "acme", plan: str = "free") -> MagicMock:
    tenant = MagicMock()
    tenant.id = uuid.uuid4()
    tenant.slug = slug
    tenant.plan = plan
    tenant.status = "active"
    return tenant


class TestProvisionSourcePolicy:
    def test_admin_provision_allows_paid_plans(self) -> None:
        svc, repo, _session = _make_service()
        repo.get_by_slug.return_value = None
        repo.create.return_value = _tenant(slug="paid-co", plan="pro")

        result = svc.provision(
            name="Paid Co",
            slug="paid-co",
            plan="pro",
            actor="admin",
            source=ProvisionSource.ADMIN,
        )

        assert result.plan == "pro"
        assert result.source == ProvisionSource.ADMIN
        repo.create.assert_called_once_with(name="Paid Co", slug="paid-co", plan="pro")

    def test_self_serve_provision_requires_free_plan(self) -> None:
        svc, repo, _session = _make_service()
        repo.get_by_slug.return_value = None

        with pytest.raises(ValueError, match="free-plan"):
            svc.provision(
                name="Bad Co",
                slug="bad-co",
                plan="pro",
                actor="signup:user@example.com",
                source=ProvisionSource.SELF_SERVE,
            )

        repo.create.assert_not_called()

    def test_self_serve_provision_emits_self_serve_governance_event(self) -> None:
        svc, repo, session = _make_service()
        repo.get_by_slug.return_value = None
        repo.create.return_value = _tenant(slug="signup-co", plan="free")

        svc.provision(
            name="Signup Co",
            slug="signup-co",
            plan="free",
            actor="signup:user@example.com",
            source=ProvisionSource.SELF_SERVE,
        )

        session.execute.assert_called()
        session.add.assert_called()
        event = session.add.call_args[0][0]
        assert event.event_type == "tenant_self_serve_provisioned"
        assert event.payload_json["source"] == "self_serve"

    def test_admin_provision_emits_admin_governance_event(self) -> None:
        svc, repo, session = _make_service()
        repo.get_by_slug.return_value = None
        repo.create.return_value = _tenant(slug="admin-co", plan="starter")

        svc.provision(
            name="Admin Co",
            slug="admin-co",
            plan="starter",
            actor="operator",
            source=ProvisionSource.ADMIN,
        )

        event = session.add.call_args[0][0]
        assert event.event_type == "tenant_provisioned"
        assert event.payload_json["source"] == "admin"

    def test_provision_activates_tenant_session_before_governance_emit(self) -> None:
        svc, repo, session = _make_service()
        tenant = _tenant(slug="rls-co", plan="free")
        repo.get_by_slug.return_value = None
        repo.create.return_value = tenant

        svc.provision(
            name="RLS Co",
            slug="rls-co",
            plan="free",
            actor="admin",
            source=ProvisionSource.ADMIN,
        )

        execute_calls = session.execute.call_args_list
        assert execute_calls
        set_config_sql = str(execute_calls[0][0][0])
        assert "set_config" in set_config_sql
        assert execute_calls[0][0][1] == {"tenant_id": str(tenant.id)}
