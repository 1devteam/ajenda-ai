from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from backend.domain.retrieval_contract import RetrievalContract
from backend.repositories.retrieval_contract_repository import RetrievalContractRepository


def test_add_flushes_and_refreshes_retrieval_contract_record() -> None:
    record = RetrievalContract(
        tenant_id="tenant-a",
        mission_id=uuid.uuid4(),
        retrieval_reason="Need relevant memory.",
        retrieval_strategy="hybrid",
    )
    session = MagicMock()

    result = RetrievalContractRepository(session).add(record)

    assert result is record
    session.add.assert_called_once_with(record)
    session.flush.assert_called_once_with()
    session.refresh.assert_called_once_with(record)


def test_get_for_tenant_uses_tenant_scoped_query() -> None:
    tenant_id = str(uuid.uuid4())
    retrieval_id = uuid.uuid4()
    record = RetrievalContract(
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        retrieval_reason="Recall approved decision.",
        retrieval_strategy="keyword",
    )
    session = MagicMock()
    session.scalar.return_value = record

    result = RetrievalContractRepository(session).get_for_tenant(retrieval_id=retrieval_id, tenant_id=tenant_id)

    assert result is record
    statement = session.scalar.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "retrieval_contracts.id" in compiled
    assert "retrieval_contracts.tenant_id" in compiled
    assert tenant_id in compiled


def test_list_for_mission_filters_by_tenant_and_mission() -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    session = MagicMock()
    session.scalars.return_value = [MagicMock()]

    result = RetrievalContractRepository(session).list_for_mission(mission_id=mission_id, tenant_id=tenant_id)

    assert result == [session.scalars.return_value[0]]
    statement = session.scalars.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "retrieval_contracts.mission_id" in compiled
    assert "retrieval_contracts.tenant_id" in compiled
    assert tenant_id in compiled


def test_update_flushes_and_refreshes_retrieval_contract_record() -> None:
    record = RetrievalContract(
        tenant_id="tenant-a",
        mission_id=uuid.uuid4(),
        retrieval_reason="Recall prior outcome.",
        retrieval_strategy="procedural",
    )
    session = MagicMock()

    result = RetrievalContractRepository(session).update(record)

    assert result is record
    session.add.assert_called_once_with(record)
    session.flush.assert_called_once_with()
    session.refresh.assert_called_once_with(record)
