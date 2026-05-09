from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from backend.domain.capability_adapter import CapabilityAdapter
from backend.repositories.capability_adapter_repository import CapabilityAdapterRepository


def test_get_visible_for_tenant_allows_tenant_or_global_scope() -> None:
    tenant_id = str(uuid.uuid4())
    adapter_id = uuid.uuid4()
    adapter = CapabilityAdapter(tenant_id=tenant_id, name="crm-adapter", version="1", supported_task_types=["crm"])
    session = MagicMock()
    session.scalar.return_value = adapter

    result = CapabilityAdapterRepository(session).get_visible_for_tenant(adapter_id=adapter_id, tenant_id=tenant_id)

    assert result is adapter
    statement = session.scalar.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "capability_adapters.id" in compiled
    assert "capability_adapters.tenant_id" in compiled
    assert "IS NULL" in compiled
    assert tenant_id in compiled


def test_list_visible_for_tenant_filters_to_tenant_or_global_scope() -> None:
    tenant_id = str(uuid.uuid4())
    session = MagicMock()
    session.scalars.return_value = [MagicMock()]

    result = CapabilityAdapterRepository(session).list_visible_for_tenant(tenant_id=tenant_id)

    assert result == [session.scalars.return_value[0]]
    statement = session.scalars.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "capability_adapters.tenant_id" in compiled
    assert "IS NULL" in compiled
    assert tenant_id in compiled


def test_get_conflict_for_scope_uses_tenant_scope_when_present() -> None:
    tenant_id = str(uuid.uuid4())
    session = MagicMock()

    CapabilityAdapterRepository(session).get_conflict_for_scope(name="crm", version="1.0.0", tenant_id=tenant_id)

    statement = session.scalar.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "capability_adapters.name = 'crm'" in compiled
    assert "capability_adapters.version = '1.0.0'" in compiled
    assert tenant_id in compiled


def test_update_flushes_and_refreshes_adapter() -> None:
    adapter = CapabilityAdapter(tenant_id="tenant-a", name="crm", version="1", supported_task_types=["crm"])
    session = MagicMock()

    result = CapabilityAdapterRepository(session).update(adapter)

    assert result is adapter
    session.add.assert_called_once_with(adapter)
    session.flush.assert_called_once_with()
    session.refresh.assert_called_once_with(adapter)
