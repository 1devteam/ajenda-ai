from unittest.mock import MagicMock

from backend.api.routes.runtime import get_runtime_mode


def test_runtime_endpoint_shape_smoke() -> None:
    payload = get_runtime_mode(MagicMock())

    assert "mode" in payload
    assert "execution_allowed" in payload
