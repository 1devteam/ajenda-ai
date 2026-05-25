from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DependencyStatus = str


@dataclass(frozen=True)
class ReadinessEvaluation:
    status_code: int
    payload: dict[str, Any]
    database_status: DependencyStatus
    queue_status: DependencyStatus


class ReadinessEvaluatorService:
    """Evaluates explicit runtime readiness truth from DB + queue dependencies."""

    def evaluate(self, *, database_runtime: Any, queue_adapter: Any) -> ReadinessEvaluation:
        database_status = self._dependency_status(database_runtime)
        queue_status = self._dependency_status(queue_adapter)

        payload: dict[str, Any] = {
            "status": "ready",
            "dependencies": {
                "database": {"status": database_status},
                "queue": {"status": queue_status},
            },
        }

        unavailable = [
            name for name, status in (("database", database_status), ("queue", queue_status)) if status == "unavailable"
        ]
        if unavailable:
            payload["status"] = "unavailable"
            if len(unavailable) == 2:
                payload["reason"] = "DEPENDENCY_UNAVAILABLE"
            elif unavailable[0] == "database":
                payload["reason"] = "DATABASE_UNAVAILABLE"
            else:
                payload["reason"] = "QUEUE_UNAVAILABLE"
            return ReadinessEvaluation(
                status_code=503,
                payload=payload,
                database_status=database_status,
                queue_status=queue_status,
            )

        return ReadinessEvaluation(
            status_code=200,
            payload=payload,
            database_status=database_status,
            queue_status=queue_status,
        )

    def _dependency_status(self, dependency: Any) -> DependencyStatus:
        if dependency is None:
            return "skipped"
        try:
            ready = bool(dependency.ping())
        except Exception:
            return "unavailable"
        return "ready" if ready else "unavailable"
