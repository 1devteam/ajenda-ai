from backend.auth.permissions import Permission


def test_permission_values_are_stable() -> None:
    assert Permission.API_KEYS_CREATE.value == "api_keys:create"
    assert Permission.EXECUTION_QUEUE.value == "execution:queue"
