from backend.auth.permissions import Permission


def test_permission_values_are_stable() -> None:
    assert Permission.API_KEYS_CREATE.value == "api_keys:create"
    assert Permission.EXECUTION_QUEUE.value == "execution:queue"
    assert Permission.MISSION_CREATE.value == "mission:create"
    assert Permission.MISSION_MANAGE.value == "mission:manage"
    assert Permission.RUNTIME_OPERATE.value == "runtime:operate"
