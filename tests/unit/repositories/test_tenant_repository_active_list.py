from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from backend.repositories.tenant_repository import TenantRepository


def test_list_active_tenant_ids_returns_active_ids_as_strings() -> None:
    active_a = uuid.uuid4()
    active_b = uuid.uuid4()
    session = MagicMock()
    session.scalars.return_value.all.return_value = [active_a, active_b]

    tenant_ids = TenantRepository(session).list_active_tenant_ids()

    assert tenant_ids == [str(active_a), str(active_b)]
