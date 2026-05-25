from unittest.mock import Mock

from backend.services.readiness_evaluator_service import ReadinessEvaluatorService


def test_readiness_evaluator_ready_when_dependencies_ping() -> None:
    db = Mock()
    db.ping.return_value = True
    queue = Mock()
    queue.ping.return_value = True

    result = ReadinessEvaluatorService().evaluate(database_runtime=db, queue_adapter=queue)

    assert result.status_code == 200
    assert result.database_status == "ready"
    assert result.queue_status == "ready"
    assert result.payload == {
        "status": "ready",
        "dependencies": {
            "database": {"status": "ready"},
            "queue": {"status": "ready"},
        },
        "reason": None,
    }


def test_readiness_evaluator_unavailable_when_database_raises() -> None:
    db = Mock()
    db.ping.side_effect = RuntimeError("db unavailable details")
    queue = Mock()
    queue.ping.return_value = True

    result = ReadinessEvaluatorService().evaluate(database_runtime=db, queue_adapter=queue)

    assert result.status_code == 503
    assert result.database_status == "unavailable"
    assert result.queue_status == "ready"
    assert result.payload["status"] == "unavailable"
    assert result.payload["reason"] == "DATABASE_UNAVAILABLE"
    assert "details" not in str(result.payload)


def test_readiness_evaluator_unavailable_when_both_dependencies_fail() -> None:
    db = Mock()
    db.ping.return_value = False
    queue = Mock()
    queue.ping.return_value = False

    result = ReadinessEvaluatorService().evaluate(database_runtime=db, queue_adapter=queue)

    assert result.status_code == 503
    assert result.payload["reason"] == "DEPENDENCY_UNAVAILABLE"


def test_readiness_evaluator_skips_none_dependencies() -> None:
    result = ReadinessEvaluatorService().evaluate(database_runtime=None, queue_adapter=None)

    assert result.status_code == 200
    assert result.database_status == "skipped"
    assert result.queue_status == "skipped"
    assert result.payload["reason"] is None
