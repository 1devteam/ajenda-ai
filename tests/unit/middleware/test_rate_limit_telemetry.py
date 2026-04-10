from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.middleware.rate_limit import _RATE_LIMIT_DECISIONS, RateLimitMiddleware
from backend.rate_limit.limiter import RateLimiter


class _Tenant:
    def __init__(self, plan: str) -> None:
        self.plan = plan


def _build_app(*, max_requests: int, plan: str = "pro") -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limiter=RateLimiter(max_requests=max_requests, window_seconds=60))

    @app.middleware("http")
    async def _inject_tenant(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.tenant_id = "tenant-a"
        request.state.principal = None
        request.state.tenant = _Tenant(plan)
        return await call_next(request)

    @app.get("/v1/webhooks/x")
    def x() -> dict[str, str]:
        return {"ok": "ok"}

    return app


def _counter_value(*, plan: str, route_class: str, outcome: str) -> float:
    return _RATE_LIMIT_DECISIONS.labels(plan=plan, route_class=route_class, outcome=outcome)._value.get()


def test_rate_limit_telemetry_counter_increments_for_allowed_requests() -> None:
    client = TestClient(_build_app(max_requests=2, plan="pro"))
    before = _counter_value(plan="pro", route_class="webhooks", outcome="allowed")
    response = client.get("/v1/webhooks/x")
    assert response.status_code == 200
    after = _counter_value(plan="pro", route_class="webhooks", outcome="allowed")
    assert after == before + 1


def test_rate_limit_telemetry_counter_increments_for_denied_requests() -> None:
    client = TestClient(_build_app(max_requests=1, plan="free"))
    client.get("/v1/webhooks/x")
    before = _counter_value(plan="free", route_class="webhooks", outcome="denied")
    denied = client.get("/v1/webhooks/x")
    assert denied.status_code == 429
    after = _counter_value(plan="free", route_class="webhooks", outcome="denied")
    assert after == before + 1
