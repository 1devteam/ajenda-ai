from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DependencyStatus = str


@dataclass(frozen=True)
class ReadinessEvaluation:
    status_code: int
    payload: dict[str, Any]
    database_status: DependencyStatus
    schema_status: DependencyStatus
    queue_status: DependencyStatus


class ReadinessEvaluatorService:
    """Evaluates explicit runtime readiness truth from DB + queue dependencies."""

    def evaluate(self, *, database_runtime: Any, queue_adapter: Any) -> ReadinessEvaluation:
        database_status = self._dependency_status(database_runtime)
        schema_status = self._schema_status(database_runtime, database_status=database_status)
        queue_status = self._dependency_status(queue_adapter)

        payload: dict[str, Any] = {
            "status": "ready",
            "dependencies": {
                "database": {"status": database_status},
                "schema": {"status": schema_status},
                "queue": {"status": queue_status},
            },
            "reason": None,
        }

        unavailable = [
            name
            for name, status in (("database", database_status), ("schema", schema_status), ("queue", queue_status))
            if status in {"behind", "unavailable"}
        ]
        if unavailable:
            payload["status"] = "unavailable"
            if schema_status == "behind":
                payload["reason"] = "SCHEMA_BEHIND"
            elif schema_status == "unavailable":
                payload["reason"] = "SCHEMA_UNAVAILABLE"
            elif len(unavailable) == 2:
                payload["reason"] = "DEPENDENCY_UNAVAILABLE"
            elif unavailable[0] == "database":
                payload["reason"] = "DATABASE_UNAVAILABLE"
            else:
                payload["reason"] = "QUEUE_UNAVAILABLE"
            return ReadinessEvaluation(
                status_code=503,
                payload=payload,
                database_status=database_status,
                schema_status=schema_status,
                queue_status=queue_status,
            )

        return ReadinessEvaluation(
            status_code=200,
            payload=payload,
            database_status=database_status,
            schema_status=schema_status,
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

    def _schema_status(self, database_runtime: Any, *, database_status: DependencyStatus) -> DependencyStatus:
        if database_runtime is None or database_status != "ready":
            return "skipped"
        try:
            status = database_runtime.schema_revision_status()
        except Exception:
            return "unavailable"
        return status if status in {"ready", "behind"} else "unavailable"
