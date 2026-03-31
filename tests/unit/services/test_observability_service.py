from backend.observability.metrics import MetricsSnapshot


def test_metrics_snapshot_dataclass_contract() -> None:
    snapshot = MetricsSnapshot(1, 2, 3, 4, 5, 6, 7, 0.5)
    assert snapshot.dead_letter_count == 4
