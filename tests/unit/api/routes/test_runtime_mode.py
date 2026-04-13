from types import SimpleNamespace

from backend.api.routes import runtime


class DummySession:
    pass


def test_runtime_endpoint_shape_smoke(monkeypatch) -> None:
    fake_decision = SimpleNamespace(
        mode=SimpleNamespace(value="normal"),
        provisioning_allowed=True,
        execution_allowed=True,
        reason="ok",
    )

    class FakeRuntimeGovernor:
        def __init__(self, db) -> None:
            self.db = db

        def evaluate(self):
            return fake_decision

    monkeypatch.setattr(runtime, "RuntimeGovernor", FakeRuntimeGovernor)

    payload = runtime.get_runtime_mode(DummySession())

    assert payload["mode"] == "normal"
    assert payload["provisioning_allowed"] is True
    assert payload["execution_allowed"] is True
    assert payload["reason"] == "ok"
