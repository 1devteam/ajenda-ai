from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from backend.services.branch_manager import BranchManager
from backend.services.workforce_provisioner import WorkforceProvisioner


class _MissionLookup:
    def __init__(self, result: object | None) -> None:
        self._result = result

    def get_for_tenant(self, *, mission_id: uuid.UUID, tenant_id: str) -> object | None:
        return self._result


class _BranchLookup:
    def __init__(self, result: object | None) -> None:
        self._result = result

    def get(self, branch_id: uuid.UUID) -> object | None:
        return self._result


def test_branch_creation_rejects_mission_not_owned_by_tenant() -> None:
    manager = object.__new__(BranchManager)
    manager._missions = _MissionLookup(None)
    manager._branches = _BranchLookup(None)

    with pytest.raises(ValueError, match="mission not found for tenant"):
        manager.create_branch(
            tenant_id="tenant-a",
            mission_id=uuid.uuid4(),
            parent_branch_id=None,
            reason="test",
        )


def test_branch_creation_rejects_parent_from_other_tenant() -> None:
    mission_id = uuid.uuid4()
    manager = object.__new__(BranchManager)
    manager._missions = _MissionLookup(SimpleNamespace(id=mission_id, tenant_id="tenant-a"))
    manager._branches = _BranchLookup(SimpleNamespace(id=uuid.uuid4(), tenant_id="tenant-b", mission_id=mission_id))

    with pytest.raises(ValueError, match="parent branch not found for tenant mission"):
        manager.create_branch(
            tenant_id="tenant-a",
            mission_id=mission_id,
            parent_branch_id=uuid.uuid4(),
            reason="test",
        )


def test_branch_creation_rejects_parent_from_different_mission() -> None:
    mission_id = uuid.uuid4()
    manager = object.__new__(BranchManager)
    manager._missions = _MissionLookup(SimpleNamespace(id=mission_id, tenant_id="tenant-a"))
    manager._branches = _BranchLookup(SimpleNamespace(id=uuid.uuid4(), tenant_id="tenant-a", mission_id=uuid.uuid4()))

    with pytest.raises(ValueError, match="parent branch not found for tenant mission"):
        manager.create_branch(
            tenant_id="tenant-a",
            mission_id=mission_id,
            parent_branch_id=uuid.uuid4(),
            reason="test",
        )


def test_workforce_provisioner_rejects_mission_not_owned_by_tenant() -> None:
    provisioner = object.__new__(WorkforceProvisioner)
    provisioner._missions = _MissionLookup(None)

    with pytest.raises(ValueError, match="mission not found for tenant"):
        provisioner.provision_fleet(
            tenant_id="tenant-a",
            mission_id=uuid.uuid4(),
            fleet_name="test fleet",
            agent_specs=[],
        )
