from __future__ import annotations

from fastapi import APIRouter, Response

router = APIRouter()


@router.get("/observability/metrics")
def metrics() -> Response:
    # minimal safe placeholder
    data = "ajenda_up 1\n"
    return Response(content=data, media_type="text/plain; version=0.0.4")
