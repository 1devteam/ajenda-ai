from __future__ import annotations

from scripts.validation.ability_rollout_contract_check import main


def test_ability_rollout_contract_check_passes_current_catalog() -> None:
    assert main() == 0
