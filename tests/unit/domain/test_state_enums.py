from backend.domain.enums import (
    ExecutionBranchState,
    ExecutionTaskState,
    MissionState,
    UserWorkforceAgentState,
    WorkerLeaseState,
    WorkforceFleetState,
)


def test_mission_states_are_canonical() -> None:
    assert [state.value for state in MissionState] == [
        "planned",
        "approved",
        "queued",
        "running",
        "paused",
        "completed",
        "failed",
        "cancelled",
        "archived",
    ]


def test_workforce_fleet_states_are_canonical() -> None:
    assert [state.value for state in WorkforceFleetState] == [
        "planned",
        "provisioning",
        "ready",
        "running",
        "paused",
        "completed",
        "failed",
        "retired",
    ]


def test_agent_states_are_canonical() -> None:
    assert [state.value for state in UserWorkforceAgentState] == [
        "planned",
        "provisioned",
        "assigned",
        "running",
        "paused",
        "completed",
        "failed",
        "retired",
    ]


def test_execution_task_states_are_canonical() -> None:
    assert [state.value for state in ExecutionTaskState] == [
        "planned",
        "queued",
        "claimed",
        "running",
        "blocked",
        "completed",
        "failed",
        "cancelled",
        "dead_lettered",
    ]


def test_execution_branch_states_are_canonical() -> None:
    assert [state.value for state in ExecutionBranchState] == [
        "open",
        "running",
        "superseded",
        "selected",
        "closed",
        "failed",
    ]


def test_worker_lease_states_are_canonical() -> None:
    assert [state.value for state in WorkerLeaseState] == [
        "claimed",
        "active",
        "expired",
        "released",
    ]
