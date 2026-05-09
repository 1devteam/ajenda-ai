from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from backend.domain.capability import Capability
from backend.repositories.capability_repository import CapabilityRepository


def test_get_visible_for_tenant_allows_tenant_or_global_scope() -> None:
    tenant_id = str(uuid.uuid4())
    capability_id = uuid.uuid4()
    capability = Capability(
        tenant_id=tenant_id, name="crm", version="1", description="CRM", supported_task_types=["crm"]
    )
    session = MagicMock()
    session.scalar.return_value = capability

    result = CapabilityRepository(session).get_visible_for_tenant(capability_id=capability_id, tenant_id=tenant_id)

    assert result is capability
    statement = session.scalar.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "capabilities.id" in compiled
    assert "capabilities.tenant_id" in compiled
    assert "IS NULL" in compiled
    assert tenant_id in compiled


def test_list_visible_for_tenant_filters_to_tenant_or_global_scope() -> None:
    tenant_id = str(uuid.uuid4())
    session = MagicMock()
    session.scalars.return_value = [MagicMock()]

    result = CapabilityRepository(session).list_visible_for_tenant(tenant_id=tenant_id)

    assert result == [session.scalars.return_value[0]]
    statement = session.scalars.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "capabilities.tenant_id" in compiled
    assert "IS NULL" in compiled
    assert tenant_id in compiled


def test_get_conflict_for_scope_uses_tenant_scope_when_present() -> None:
    tenant_id = str(uuid.uuid4())
    session = MagicMock()

    CapabilityRepository(session).get_conflict_for_scope(name="crm", version="1.0.0", tenant_id=tenant_id)

    statement = session.scalar.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "capabilities.name = 'crm'" in compiled
    assert "capabilities.version = '1.0.0'" in compiled
    assert tenant_id in compiled


def test_update_flushes_and_refreshes_capability() -> None:
    capability = Capability(
        tenant_id="tenant-a", name="crm", version="1", description="CRM", supported_task_types=["crm"]
    )
    session = MagicMock()

    result = CapabilityRepository(session).update(capability)

    assert result is capability
    session.add.assert_called_once_with(capability)
    session.flush.assert_called_once_with()
    session.refresh.assert_called_once_with(capability)
