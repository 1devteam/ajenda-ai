from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from backend.workers.worker_loop import WorkerLoop


def test_claim_and_start_task_activates_tenant_rls_context() -> None:
    tenant_id = str(uuid.uuid4())
    session = MagicMock()
    session_factory = MagicMock(return_value=session)
    runtime = MagicMock()
    runtime.claim_next_task.return_value = None

    loop = WorkerLoop(
        session_factory=session_factory,
        queue=MagicMock(),
        worker_id="worker-1",
        tenant_id=tenant_id,
    )

    with (
        patch("backend.workers.worker_loop.activate_tenant_session") as activate,
        patch("backend.workers.worker_loop.WorkerRuntimeService", return_value=runtime),
    ):
        assert loop._claim_and_start_task() is None

    activate.assert_called_once_with(session, tenant_id)
    runtime.claim_next_task.assert_called_once()


def test_claim_and_start_reactivates_tenant_rls_after_durable_claim() -> None:
    tenant_id = str(uuid.uuid4())
    task_id = uuid.uuid4()
    lease_id = uuid.uuid4()
    session = MagicMock()
    session_factory = MagicMock(return_value=session)
    runtime = MagicMock()
    runtime.claim_next_task.return_value = MagicMock(
        id=task_id,
        metadata_json={"worker_lease_id": str(lease_id)},
    )

    loop = WorkerLoop(
        session_factory=session_factory,
        queue=MagicMock(),
        worker_id="worker-1",
        tenant_id=tenant_id,
    )

    with (
        patch("backend.workers.worker_loop.activate_tenant_session") as activate,
        patch("backend.workers.worker_loop.WorkerRuntimeService", return_value=runtime),
    ):
        assert loop._claim_and_start_task() == (task_id, lease_id)

    assert activate.call_args_list == [
        ((session, tenant_id),),
        ((session, tenant_id),),
        ((session, tenant_id),),
    ]
    runtime.heartbeat.assert_called_once_with(tenant_id=tenant_id, lease_id=lease_id, worker_id="worker-1")
    runtime.start_execution.assert_called_once_with(tenant_id=tenant_id, lease_id=lease_id, worker_id="worker-1")
