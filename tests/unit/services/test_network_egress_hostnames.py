from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from backend.services.network_egress import NetworkEgressAuthority, NetworkEgressError


def test_public_hostname_with_metadata_substring_is_vetted_by_dns_not_name_heuristic() -> None:
    public_answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
    with patch("backend.services.network_egress.socket.getaddrinfo", return_value=public_answer):
        destination = NetworkEgressAuthority().vet_https_url("https://metadata.example/path")

    assert str(destination.pinned_ip) == "8.8.8.8"
    assert destination.sni_hostname == "metadata.example"


@pytest.mark.parametrize("host", ["internal.example", "metadata.example"])
def test_hostname_words_do_not_override_private_dns_rejection(host: str) -> None:
    private_answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443))]
    with patch("backend.services.network_egress.socket.getaddrinfo", return_value=private_answer):
        with pytest.raises(NetworkEgressError, match="private DNS resolution"):
            NetworkEgressAuthority().vet_https_url(f"https://{host}/")
