from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.middleware.rate_limit import RateLimitMiddleware
from backend.rate_limit.limiter import RateLimiter


class _Tenant:
    def __init__(self, plan: str) -> None:
        self.plan = plan


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limiter=RateLimiter(max_requests=2, window_seconds=60))

    @app.middleware("http")
    async def _inject_tenant(request: Request, call_next):  # type: ignore[no-untyped-def]
        plan = request.headers.get("X-Test-Plan")
        request.state.tenant_id = "tenant-a"
        request.state.principal = None
        request.state.tenant = _Tenant(plan) if plan else None
        return await call_next(request)

    @app.get("/x")
    def x() -> dict[str, str]:
        return {"ok": "ok"}

    return app


def test_free_plan_uses_base_limit() -> None:
    client = TestClient(_build_app())
    assert client.get("/x", headers={"X-Test-Plan": "free"}).status_code == 200
    assert client.get("/x", headers={"X-Test-Plan": "free"}).status_code == 200
    denied = client.get("/x", headers={"X-Test-Plan": "free"})
    assert denied.status_code == 429


def test_pro_plan_gets_adaptive_burst_and_multiplier() -> None:
    client = TestClient(_build_app())
    # base=2, pro multiplier=1.75, burst=5 => floor(3.5)+5 = 8
    for _ in range(8):
        allowed = client.get("/x", headers={"X-Test-Plan": "pro"})
        assert allowed.status_code == 200
        assert allowed.headers["X-RateLimit-Limit"] == "8"
        assert allowed.headers["X-RateLimit-Plan"] == "pro"

    denied = client.get("/x", headers={"X-Test-Plan": "pro"})
    assert denied.status_code == 429
