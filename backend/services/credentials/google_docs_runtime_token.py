"""Google Docs OAuth bundle serialization and runtime token extraction."""

from __future__ import annotations

import json

from backend.services.tools.google_docs_provider import required_google_docs_scopes
from backend.services.tools.google_oauth_cli import GoogleOAuthTokenBundle

PROVIDER_KIND = "google_docs"


def serialize_google_docs_oauth_secret(*, bundle: GoogleOAuthTokenBundle) -> str:
    return json.dumps(
        {
            "provider_kind": PROVIDER_KIND,
            "access_token": bundle.access_token,
            "refresh_token": bundle.refresh_token,
            "expires_at": bundle.expires_at,
            "scopes": list(bundle.scopes or required_google_docs_scopes()),
            "token_type": bundle.token_type,
        },
        sort_keys=True,
    )
