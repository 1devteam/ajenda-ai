from __future__ import annotations

from backend.domain.enums import (
    ExecutionBranchState,
    ExecutionTaskState,
    UserWorkforceAgentState,
    WorkerLeaseState,
    WorkforceFleetState,
)
from backend.domain.execution_branch import ExecutionBranch
from backend.domain.execution_task import ExecutionTask
from backend.domain.user_workforce_agent import UserWorkforceAgent
from backend.domain.worker_lease import WorkerLease
from backend.domain.workforce_fleet import WorkforceFleet
from backend.runtime.state_machine import StateMachine


def transition_task(task: ExecutionTask, target: ExecutionTaskState) -> ExecutionTask:
    StateMachine.ensure_task_transition(task.status, target.value)
    task.status = target.value
    return task


def transition_fleet(fleet: WorkforceFleet, target: WorkforceFleetState) -> WorkforceFleet:
    StateMachine.ensure_fleet_transition(fleet.status, target.value)
    fleet.status = target.value
    return fleet


def transition_agent(agent: UserWorkforceAgent, target: UserWorkforceAgentState) -> UserWorkforceAgent:
    StateMachine.ensure_agent_transition(agent.status, target.value)
    agent.status = target.value
    return agent


def transition_branch(branch: ExecutionBranch, target: ExecutionBranchState) -> ExecutionBranch:
    StateMachine.ensure_branch_transition(branch.status, target.value)
    branch.status = target.value
    return branch


def transition_lease(lease: WorkerLease, target: WorkerLeaseState) -> WorkerLease:
    StateMachine.ensure_lease_transition(lease.status, target.value)
    lease.status = target.value
    return lease
