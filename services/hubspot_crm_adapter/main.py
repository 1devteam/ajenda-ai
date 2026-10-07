"""Ajenda generic CRM adapter → HubSpot API.

Implements the contract expected by:
- backend/services/tools/sales_actions.py (GET /v1/search)
- backend/services/tools/gtm_actions.py (POST /v1/upsert)

Ajenda workers call these paths on trusted_destination_hosts[0] with
Authorization: Bearer <tenant credential secret>. This service forwards
that token to https://api.hubapi.com.

Note: Ajenda NetworkEgressAuthority requires HTTPS URLs whose hostnames resolve
to public routable addresses. For local docker-compose, point
trusted_destination_hosts at a public hostname (or TLS-terminated ingress)
that routes to this service — private service DNS names are blocked by egress.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Header, HTTPException, Path, Query, Request

from services.hubspot_crm_adapter.hubspot import (
    RECORD_TYPE_TO_OBJECT,
    HubSpotApiError,
    HubSpotClient,
    bearer_token_from_header,
)
from services.hubspot_crm_adapter.models import ReadResponse, SearchResponse, UpsertRequest, UpsertResponse

app = FastAPI(
    title="HubSpot CRM Adapter",
    version="1.0.0",
    description="Ajenda generic CRM gateway (/v1/search, /v1/upsert) for HubSpot",
)

HUBSPOT_API_BASE = os.getenv("HUBSPOT_API_BASE", "https://api.hubapi.com")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("HUBSPOT_ADAPTER_TIMEOUT_SECONDS", "15"))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "adapter": "hubspot-crm", "upstream": HUBSPOT_API_BASE}


@app.get("/v1/search", response_model=SearchResponse)
async def search(
    company: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
) -> SearchResponse:
    try:
        token = bearer_token_from_header(authorization)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    client = HubSpotClient(
        access_token=token,
        api_base=HUBSPOT_API_BASE,
        timeout_seconds=REQUEST_TIMEOUT_SECONDS,
    )
    try:
        object_type, results = client.search(company=company, domain=domain)
    except HubSpotApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return SearchResponse(results=results, count=len(results), object_type=object_type)


@app.post("/v1/upsert", response_model=UpsertResponse)
async def upsert(
    body: UpsertRequest,
    request: Request,
    authorization: str | None = Header(default=None),
) -> UpsertResponse:
    try:
        token = bearer_token_from_header(authorization)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    client = HubSpotClient(
        access_token=token,
        api_base=HUBSPOT_API_BASE,
        timeout_seconds=REQUEST_TIMEOUT_SECONDS,
    )
    try:
        result = client.upsert(record_type=body.record_type, data=body.data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HubSpotApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    # Ajenda may send Idempotency-Key header; HubSpot has no native equivalent for CRM v3.
    _ = request.headers.get("Idempotency-Key") or body.idempotency_key

    return UpsertResponse(**result)


@app.get("/v1/records/{record_type}/{record_id}", response_model=ReadResponse)
async def read_record(
    record_type: str = Path(min_length=1, max_length=80),
    record_id: str = Path(min_length=1, max_length=160),
    authorization: str | None = Header(default=None),
) -> ReadResponse:
    try:
        token = bearer_token_from_header(authorization)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    client = HubSpotClient(
        access_token=token,
        api_base=HUBSPOT_API_BASE,
        timeout_seconds=REQUEST_TIMEOUT_SECONDS,
    )
    try:
        payload = client.read(record_type=record_type, record_id=record_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HubSpotApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    normalized_type = record_type.strip().lower()
    object_type = RECORD_TYPE_TO_OBJECT.get(normalized_type)
    if object_type is None:
        raise HTTPException(status_code=400, detail=f"unsupported record_type: {record_type}")
    return ReadResponse(
        record_type=normalized_type,
        hubspot_object_type=object_type,
        id=str(payload.get("id", record_id)),
        properties=payload.get("properties", {}) if isinstance(payload.get("properties", {}), dict) else {},
    )
