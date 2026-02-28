"""
Tests for Phase 4.2 Security Hardening
Covers: SecurityHeadersMiddleware, input sanitisation, secrets validator.
Built with Pride for Obex Blackvault
"""

import pytest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


# ── SecurityHeadersMiddleware ─────────────────────────────────────────────────


class TestSecurityHeadersMiddleware:
    """Tests for HTTP security headers applied to all responses."""

    def _make_app(self, environment: str = "development") -> FastAPI:
        from backend.middleware.security_headers import SecurityHeadersMiddleware

        app = FastAPI()

        @app.get("/api/v1/test")
        def test_endpoint():
            return {"ok": True}

        @app.get("/health")
        def health():
            return {"status": "ok"}

        # Pass environment directly to avoid patching module-level settings
        app.add_middleware(SecurityHeadersMiddleware, environment=environment)
        return app

    def test_x_content_type_options_present(self):
        app = self._make_app()
        client = TestClient(app, raise_server_exceptions=True)
        response = client.get("/api/v1/test")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options_deny(self):
        app = self._make_app()
        client = TestClient(app)
        response = client.get("/api/v1/test")
        assert response.headers.get("X-Frame-Options") == "DENY"

    def test_referrer_policy_present(self):
        app = self._make_app()
        client = TestClient(app)
        response = client.get("/api/v1/test")
        assert "strict-origin-when-cross-origin" in response.headers.get("Referrer-Policy", "")

    def test_permissions_policy_present(self):
        app = self._make_app()
        client = TestClient(app)
        response = client.get("/api/v1/test")
        assert "geolocation=()" in response.headers.get("Permissions-Policy", "")

    def test_csp_present(self):
        app = self._make_app()
        client = TestClient(app)
        response = client.get("/api/v1/test")
        assert "Content-Security-Policy" in response.headers

    def test_api_cache_control_no_store(self):
        app = self._make_app()
        client = TestClient(app)
        response = client.get("/api/v1/test")
        assert "no-store" in response.headers.get("Cache-Control", "")

    def test_health_endpoint_no_cache_control(self):
        """Health endpoint is not under /api/ so should not get cache-control."""
        app = self._make_app()
        client = TestClient(app)
        response = client.get("/health")
        # Cache-Control should not be set for non-API paths
        assert "no-store" not in response.headers.get("Cache-Control", "")

    def test_hsts_only_in_production(self):
        dev_app = self._make_app(environment="development")
        prod_app = self._make_app(environment="production")

        dev_client = TestClient(dev_app)
        prod_client = TestClient(prod_app)

        dev_response = dev_client.get("/api/v1/test")
        prod_response = prod_client.get("/api/v1/test")

        assert "Strict-Transport-Security" not in dev_response.headers
        assert "Strict-Transport-Security" in prod_response.headers
        assert "max-age=63072000" in prod_response.headers["Strict-Transport-Security"]


# ── Input Sanitisation ────────────────────────────────────────────────────────


class TestSanitiseString:
    """Tests for sanitise_string()."""

    def test_html_escaping(self):
        from backend.security.sanitisation import sanitise_string

        result = sanitise_string('<script>alert("xss")</script>')
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_null_byte_removal(self):
        from backend.security.sanitisation import sanitise_string

        result = sanitise_string("hello\x00world")
        assert "\x00" not in result
        assert "helloworld" in result

    def test_truncation(self):
        from backend.security.sanitisation import sanitise_string

        long_string = "a" * 20_000
        result = sanitise_string(long_string, max_length=100)
        assert len(result) == 100

    def test_allow_html_skips_escaping(self):
        from backend.security.sanitisation import sanitise_string

        result = sanitise_string("<b>bold</b>", allow_html=True)
        assert "<b>bold</b>" in result

    def test_normal_string_unchanged(self):
        from backend.security.sanitisation import sanitise_string

        result = sanitise_string("Hello, World!")
        assert result == "Hello, World!"

    def test_non_string_passthrough(self):
        from backend.security.sanitisation import sanitise_string

        assert sanitise_string(42) == 42  # type: ignore[arg-type]


class TestSanitiseDict:
    """Tests for sanitise_dict()."""

    def test_nested_string_sanitised(self):
        from backend.security.sanitisation import sanitise_dict

        data = {"name": "<img src=x onerror=alert(1)>", "nested": {"val": "<b>hi</b>"}}
        result = sanitise_dict(data)
        assert "<img" not in result["name"]
        assert "<b>" not in result["nested"]["val"]

    def test_non_string_values_preserved(self):
        from backend.security.sanitisation import sanitise_dict

        data = {"count": 42, "active": True, "score": 3.14}
        result = sanitise_dict(data)
        assert result["count"] == 42
        assert result["active"] is True
        assert result["score"] == 3.14

    def test_list_values_sanitised(self):
        from backend.security.sanitisation import sanitise_dict

        data = {"tags": ["<script>bad</script>", "normal"]}
        result = sanitise_dict(data)
        assert "<script>" not in result["tags"][0]
        assert result["tags"][1] == "normal"

    def test_max_depth_protection(self):
        from backend.security.sanitisation import sanitise_dict

        # Build a deeply nested dict (11 levels)
        deep: dict = {}
        current = deep
        for _ in range(11):
            current["child"] = {}
            current = current["child"]
        current["value"] = "leaf"
        # Should not raise; just truncate at max_depth
        result = sanitise_dict(deep, max_depth=5)
        assert isinstance(result, dict)


class TestSanitiseHtml:
    """Tests for sanitise_html()."""

    def test_script_tag_removed(self):
        from backend.security.sanitisation import sanitise_html

        result = sanitise_html("<p>Hello</p><script>alert(1)</script>")
        assert "<script>" not in result
        assert "<p>Hello</p>" in result

    def test_event_handler_removed(self):
        from backend.security.sanitisation import sanitise_html

        result = sanitise_html('<div onclick="evil()">click me</div>')
        assert "onclick" not in result

    def test_javascript_protocol_removed(self):
        from backend.security.sanitisation import sanitise_html

        result = sanitise_html('<a href="javascript:void(0)">link</a>')
        assert "javascript:" not in result


# ── Secrets Validator ─────────────────────────────────────────────────────────


class TestSecretsValidator:
    """Tests for validate_secrets()."""

    def test_development_mode_warns_but_does_not_raise(self):
        """In development, weak secrets should log warnings but not raise."""
        from backend.security.secrets_validator import validate_secrets

        with patch.dict("os.environ", {"JWT_SECRET_KEY": "weak", "SECRET_KEY": "weak"}):
            # Should not raise
            validate_secrets(environment="development")

    def test_production_mode_raises_on_insecure_default(self):
        """In production, insecure defaults must raise SecretsValidationError."""
        from backend.security.secrets_validator import (
            validate_secrets,
            SecretsValidationError,
        )

        with patch.dict(
            "os.environ",
            {
                "JWT_SECRET_KEY": "changeme",
                "SECRET_KEY": "changeme",
            },
        ):
            with pytest.raises(SecretsValidationError):
                validate_secrets(environment="production")

    def test_production_mode_raises_on_missing_secret(self):
        """In production, unset secrets must raise SecretsValidationError."""
        from backend.security.secrets_validator import (
            validate_secrets,
            SecretsValidationError,
        )

        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(SecretsValidationError):
                validate_secrets(environment="production")

    def test_production_mode_passes_with_strong_secrets(self):
        """In production, strong secrets should pass validation."""
        from backend.security.secrets_validator import validate_secrets

        strong = "a" * 64  # 64 chars, well above minimum
        with patch.dict(
            "os.environ",
            {
                "JWT_SECRET_KEY": strong,
                "SECRET_KEY": strong,
                "DATABASE_URL": "postgresql://user:StrongPass123!@host:5432/db",
                "REDIS_URL": "redis://:StrongPass123!@host:6379/0",
            },
        ):
            # Should not raise
            validate_secrets(environment="production")

    def test_production_raises_on_short_secret(self):
        """Secrets shorter than 32 chars must fail in production."""
        from backend.security.secrets_validator import (
            validate_secrets,
            SecretsValidationError,
        )

        short = "tooshort"
        with patch.dict(
            "os.environ",
            {
                "JWT_SECRET_KEY": short,
                "SECRET_KEY": short,
            },
        ):
            with pytest.raises(SecretsValidationError):
                validate_secrets(environment="production")
