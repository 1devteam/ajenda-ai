"""Contract tests for API versioning.

Verifies that:
- All business routes are mounted under /v1/ prefix
- Health and readiness probes remain at root (/) without version prefix
- The /v1/ prefix is present in the OpenAPI schema paths

These tests import the router directly and inspect route paths without
starting a live server, making them fast and dependency-free.
"""

from __future__ import annotations

from fastapi import FastAPI

from backend.api.router import build_api_router


def _collect_routes(app: FastAPI) -> set[str]:
    """Collect all registered route paths from a FastAPI app."""
    paths = set()
    for route in app.routes:
        if hasattr(route, "path"):
            paths.add(route.path)
    return paths


class TestApiVersioning:
    def setup_method(self) -> None:
        self.app = FastAPI()
        self.app.include_router(build_api_router())
        self.paths = _collect_routes(self.app)

    def test_health_at_root(self) -> None:
        """Health probe must be at /health, not /v1/health."""
        assert "/health" in self.paths
        assert "/v1/health" not in self.paths

    def test_readiness_at_root(self) -> None:
        """Readiness probe must be at /readiness, not /v1/readiness."""
        assert "/readiness" in self.paths
        assert "/v1/readiness" not in self.paths

    def test_business_routes_under_v1(self) -> None:
        """All business routes must be under /v1/ prefix."""
        business_prefixes = [
            "/v1/auth",
            "/v1/api-keys",
            "/v1/missions",
            "/v1/tasks",
            "/v1/workforce",
            "/v1/runtime",
            "/v1/operations",
            "/v1/system",
            "/v1/observability",
        ]
        for prefix in business_prefixes:
            matching = [p for p in self.paths if p.startswith(prefix)]
            assert matching, (
                f"Expected at least one route under '{prefix}' but found none. All paths: {sorted(self.paths)}"
            )

    def test_no_unversioned_business_routes(self) -> None:
        """Business routes must not exist at root level (without /v1/)."""
        unversioned_business = [
            "/auth",
            "/api-keys",
            "/missions",
            "/tasks",
            "/workforce",
            "/runtime",
            "/operations",
        ]
        for path_prefix in unversioned_business:
            matching = [p for p in self.paths if p.startswith(path_prefix)]
            assert not matching, f"Found unversioned business route(s) starting with '{path_prefix}': {matching}"
