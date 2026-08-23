"""Google Docs connector contract for read-only known-document access."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from backend.services.network_egress import get_default_network_egress_authority

GOOGLE_DOCS_READONLY_SCOPE = "https://www.googleapis.com/auth/documents.readonly"
GOOGLE_DOCS_API_HOST = "docs.googleapis.com"


def required_google_docs_scopes() -> tuple[str, ...]:
    """Only request read access to a document explicitly supplied by the user."""

    return (GOOGLE_DOCS_READONLY_SCOPE,)


class GoogleDocsProvider:
    """Minimal provider boundary; discovery/editing is intentionally not implied."""

    def __init__(self, *, access_token: str) -> None:
        self._access_token = access_token.strip()
        if not self._access_token:
            raise ValueError("Google Docs access token is required")

    def read_document(self, *, document_id: str) -> dict[str, Any]:
        if not document_id.strip():
            raise ValueError("Google Docs document_id is required")
        _destination, response = get_default_network_egress_authority().request(
            method="GET",
            url=f"https://docs.googleapis.com/v1/documents/{quote(document_id.strip(), safe='')}",
            headers={"Authorization": f"Bearer {self._access_token}"},
            allowed_hosts=[GOOGLE_DOCS_API_HOST],
            action_name="google_docs.document_read",
            timeout_seconds=15.0,
        )
        if not 200 <= response.status_code < 300:
            raise ValueError(f"Google Docs API returned HTTP {response.status_code}")
        payload = json.loads(response.body_text or "{}")
        if not isinstance(payload, dict):
            raise ValueError("Google Docs API returned a non-object payload")
        return payload
