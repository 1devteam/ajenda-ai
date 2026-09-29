from scripts.validation.graft_drift_controls import validate_drift_controls


def test_graft_drift_controls_are_current_and_non_authoritative() -> None:
    assert validate_drift_controls() == []
