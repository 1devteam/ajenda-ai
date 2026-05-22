from backend.services.system_status_service import SystemStatusService


def test_service_class_exists() -> None:
    assert SystemStatusService is not None


class _ReadyDependency:
    def ping(self) -> bool:
        return True


class _FalseDependency:
    def ping(self) -> bool:
        return False


class _RaisingDependency:
    def ping(self) -> bool:
        raise RuntimeError("postgresql://user:password@db.internal redis://internal-host/0 token secret Traceback")


def test_readiness_success_when_both_dependencies_ready() -> None:
    status_code, payload = SystemStatusService().readiness(
        database_runtime=_ReadyDependency(),
        queue_adapter=_ReadyDependency(),
    )
    assert status_code == 200
    assert payload == {
        "status": "ready",
        "dependencies": {"database": {"status": "ready"}, "queue": {"status": "ready"}},
    }


def test_readiness_returns_503_for_missing_or_bad_dependencies_without_leaks() -> None:
    service = SystemStatusService()
    checks = [
        service.readiness(database_runtime=None, queue_adapter=_ReadyDependency()),
        service.readiness(database_runtime=_ReadyDependency(), queue_adapter=None),
        service.readiness(database_runtime=_RaisingDependency(), queue_adapter=_ReadyDependency()),
        service.readiness(database_runtime=_ReadyDependency(), queue_adapter=_RaisingDependency()),
        service.readiness(database_runtime=_FalseDependency(), queue_adapter=_ReadyDependency()),
        service.readiness(database_runtime=_ReadyDependency(), queue_adapter=_FalseDependency()),
    ]

    banned = ["postgresql://", "redis://", "password", "token", "secret", "internal-host", "db.internal", "Traceback"]
    allowed_reasons = {"DATABASE_UNAVAILABLE", "QUEUE_UNAVAILABLE", "DEPENDENCY_UNAVAILABLE"}
    for status_code, payload in checks:
        assert status_code == 503
        assert payload["status"] == "unavailable"
        assert payload["reason"] in allowed_reasons
        text = str(payload)
        assert not any(marker in text for marker in banned)
