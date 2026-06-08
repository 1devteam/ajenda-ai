"""Role contracts for guided ability orchestration.

These contracts define what named agent roles may decide or describe. They do
not grant runtime execution authority. Runtime execution remains owned by the
queue, TaskDispatcher, tool.invoke handler, and WorkerRuntimeService.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RoleName(StrEnum):
    """Supported non-runtime orchestration roles."""

    COMMANDER = "commander"
    ARCHIVIST = "archivist"
    GUARDIAN = "guardian"


class RoleContract(BaseModel):
    """Static permission boundary for a named agent role."""

    model_config = ConfigDict(extra="forbid")

    role_name: RoleName
    may: tuple[str, ...]
    must_not: tuple[str, ...]
    may_invoke_tools: bool = False
    may_mutate_runtime: bool = False
    may_approve_side_effects: bool = False
    notes: str = Field(min_length=1, max_length=1000)


COMMANDER_ROLE_CONTRACT = RoleContract(
    role_name=RoleName.COMMANDER,
    may=(
        "propose mission and task graphs",
        "select candidate abilities for runtime consideration",
        "explain ability fit and sequencing",
    ),
    must_not=(
        "invoke tools directly",
        "bypass TaskDispatcher or WorkerRuntimeService",
        "approve its own side-effect authorization",
    ),
    notes="Commander proposes and selects; runtime still executes through tool.invoke.",
)

ARCHIVIST_ROLE_CONTRACT = RoleContract(
    role_name=RoleName.ARCHIVIST,
    may=(
        "read lineage records",
        "read evidence records",
        "read retrieval outputs",
        "summarize evidence and runtime outcomes",
    ),
    must_not=(
        "mutate runtime state",
        "invoke tools directly",
        "approve side-effect authorization",
    ),
    notes="Archivist observes and summarizes evidence; it does not mutate runtime.",
)

GUARDIAN_ROLE_CONTRACT = RoleContract(
    role_name=RoleName.GUARDIAN,
    may=(
        "classify ability risk",
        "approve side-effect authorization",
        "block unsafe ability execution",
    ),
    must_not=(
        "execute tools directly",
        "bypass queue or lease authority",
        "mutate provider state",
    ),
    may_approve_side_effects=True,
    notes="Guardian approves or blocks side-effect authorization; workers still execute.",
)


ROLE_CONTRACTS: tuple[RoleContract, ...] = (
    COMMANDER_ROLE_CONTRACT,
    ARCHIVIST_ROLE_CONTRACT,
    GUARDIAN_ROLE_CONTRACT,
)


def get_role_contract(role_name: RoleName) -> RoleContract:
    """Return a role contract by role name."""

    for contract in ROLE_CONTRACTS:
        if contract.role_name == role_name:
            return contract
    raise ValueError(f"unknown role contract: {role_name}")
