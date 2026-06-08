from __future__ import annotations

from backend.services.abilities.role_contracts import (
    ARCHIVIST_ROLE_CONTRACT,
    COMMANDER_ROLE_CONTRACT,
    GUARDIAN_ROLE_CONTRACT,
    ROLE_CONTRACTS,
    RoleName,
    get_role_contract,
)


def test_commander_role_cannot_invoke_tools_or_approve_side_effects() -> None:
    assert COMMANDER_ROLE_CONTRACT.role_name == RoleName.COMMANDER
    assert COMMANDER_ROLE_CONTRACT.may_invoke_tools is False
    assert COMMANDER_ROLE_CONTRACT.may_mutate_runtime is False
    assert COMMANDER_ROLE_CONTRACT.may_approve_side_effects is False
    assert "invoke tools directly" in COMMANDER_ROLE_CONTRACT.must_not


def test_archivist_role_is_read_only_runtime_observer() -> None:
    assert ARCHIVIST_ROLE_CONTRACT.role_name == RoleName.ARCHIVIST
    assert ARCHIVIST_ROLE_CONTRACT.may_invoke_tools is False
    assert ARCHIVIST_ROLE_CONTRACT.may_mutate_runtime is False
    assert ARCHIVIST_ROLE_CONTRACT.may_approve_side_effects is False
    assert "read evidence records" in ARCHIVIST_ROLE_CONTRACT.may


def test_guardian_role_can_approve_but_not_execute_tools() -> None:
    assert GUARDIAN_ROLE_CONTRACT.role_name == RoleName.GUARDIAN
    assert GUARDIAN_ROLE_CONTRACT.may_approve_side_effects is True
    assert GUARDIAN_ROLE_CONTRACT.may_invoke_tools is False
    assert GUARDIAN_ROLE_CONTRACT.may_mutate_runtime is False
    assert "execute tools directly" in GUARDIAN_ROLE_CONTRACT.must_not


def test_role_contract_lookup_returns_known_contracts() -> None:
    assert get_role_contract(RoleName.COMMANDER) == COMMANDER_ROLE_CONTRACT
    assert get_role_contract(RoleName.ARCHIVIST) == ARCHIVIST_ROLE_CONTRACT
    assert get_role_contract(RoleName.GUARDIAN) == GUARDIAN_ROLE_CONTRACT


def test_role_contracts_are_unique_and_non_runtime_executors() -> None:
    role_names = {contract.role_name for contract in ROLE_CONTRACTS}

    assert role_names == {RoleName.COMMANDER, RoleName.ARCHIVIST, RoleName.GUARDIAN}
    assert all(contract.may_invoke_tools is False for contract in ROLE_CONTRACTS)
    assert all(contract.may_mutate_runtime is False for contract in ROLE_CONTRACTS)
