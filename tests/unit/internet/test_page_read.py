from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.services.internet.page_read import extract_html_snapshot, fetch_public_page, normalize_page_url
from backend.services.network_egress import NetworkEgressResponse, VettedNetworkDestination


def test_normalize_page_url_adds_https_for_domain() -> None:
    assert normalize_page_url("example.com") == "https://example.com/"


def test_normalize_page_url_rejects_http() -> None:
    try:
        normalize_page_url("http://example.com")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "https" in str(exc)


def test_extract_html_snapshot_title_and_text() -> None:
    html = """
    <html><head>
      <title>Acme Corp</title>
      <meta name="description" content="Acme builds robots.">
      <script>evil()</script>
    </head><body><h1>Welcome</h1><p>We ship bots.</p></body></html>
    """
    extracted = extract_html_snapshot(html)
    assert extracted["title"] == "Acme Corp"
    assert "Acme builds robots" in (extracted["text_preview"] or "")
    assert "We ship bots" in (extracted["text_preview"] or "")
    assert "evil" not in (extracted["text_preview"] or "")


def test_fetch_public_page_uses_egress_and_extracts() -> None:
    destination = VettedNetworkDestination(
        original_url="https://example.com/",
        connect_url="https://1.2.3.4/",
        pinned_ip=__import__("ipaddress").ip_address("1.2.3.4"),
        sni_hostname="example.com",
        host_header="example.com",
    )
    response = NetworkEgressResponse(
        status_code=200,
        headers={"content-type": "text/html"},
        body_text="<html><head><title>Example Domain</title></head><body>Example body</body></html>",
        body_truncated=False,
    )
    authority = MagicMock()
    authority.request.return_value = (destination, response)

    with patch(
        "backend.services.internet.page_read.get_default_network_egress_authority",
        return_value=authority,
    ):
        snapshot = fetch_public_page(url_or_domain="example.com", timeout_seconds=5.0)

    assert snapshot.real is True
    assert snapshot.title == "Example Domain"
    assert snapshot.access_mode.value == "page_read"
    assert snapshot.browser_ready is False
    assert "Example body" in (snapshot.text_preview or "")
