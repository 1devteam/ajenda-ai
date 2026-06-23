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
