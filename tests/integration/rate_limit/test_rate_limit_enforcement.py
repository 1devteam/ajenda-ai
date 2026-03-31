from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.middleware.rate_limit import RateLimitMiddleware
from backend.rate_limit.limiter import RateLimiter


def test_rate_limit_enforcement() -> None:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limiter=RateLimiter(max_requests=1, window_seconds=60))

    @app.get("/x")
    def x() -> dict[str, str]:
        return {"ok": "ok"}

    client = TestClient(app)
    assert client.get("/x").status_code == 200
    assert client.get("/x").status_code == 429
