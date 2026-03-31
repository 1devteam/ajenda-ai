from backend.api.routes.runtime import get_runtime_mode


def test_runtime_endpoint_shape_smoke(db_session):
    payload = get_runtime_mode(db_session)
    assert "mode" in payload
    assert "execution_allowed" in payload
