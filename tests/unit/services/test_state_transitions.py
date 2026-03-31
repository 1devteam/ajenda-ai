from backend.domain.enums import ExecutionTaskState, WorkforceFleetState
from backend.services.fleet_manager import FleetManager


def test_execution_task_transition_vocab_includes_dead_lettered() -> None:
    assert ExecutionTaskState.DEAD_LETTERED.value == "dead_lettered"


def test_fleet_state_vocab_includes_ready() -> None:
    assert WorkforceFleetState.READY.value == "ready"
