from __future__ import annotations

import uuid

import pytest

from backend.runtime.claim_holders import worker_bridge_holder, worker_daemon_holder


def test_worker_daemon_holder_returns_worker_id() -> None:
    assert worker_daemon_holder(worker_id="worker-prod-1") == "worker-prod-1"


def test_worker_bridge_holder_formats_mission_scoped_identity() -> None:
    mission_id = uuid.uuid4()
    assert worker_bridge_holder(tenant_id="tenant-a", mission_id=mission_id) == (
        f"worker_claim_admission:tenant-a:{mission_id}"
    )


def test_worker_daemon_holder_rejects_empty_worker_id() -> None:
    with pytest.raises(ValueError, match="worker_id must be non-empty"):
        worker_daemon_holder(worker_id="   ")
