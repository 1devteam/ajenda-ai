from __future__ import annotations

import pytest

from backend.services.tools.http_actions import validate_safe_http_url


def test_http_url_validation_allows_public_https_with_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))]
    )

    assert (
        validate_safe_http_url("https://example.com/path", allowed_hosts=["example.com"]) == "https://example.com/path"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://localhost/status",
        "https://service.local/status",
        "https://internal-api.example.com/status",
        "https://127.0.0.1/status",
        "https://10.1.2.3/status",
        "https://169.254.169.254/latest/meta-data",
    ],
)
def test_http_url_validation_blocks_internal_targets(url: str) -> None:
    with pytest.raises(ValueError, match=r"http\.request"):
        validate_safe_http_url(url)


def test_http_url_validation_blocks_private_dns_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("socket.getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("10.0.0.4", 443))])

    with pytest.raises(ValueError, match="private DNS"):
        validate_safe_http_url("https://example.com")
