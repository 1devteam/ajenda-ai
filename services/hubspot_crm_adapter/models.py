from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RecordType = Literal["contact", "lead", "company", "deal"]


class UpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_type: str = Field(min_length=1, max_length=80)
    data: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=200)


class SearchResponse(BaseModel):
    results: list[dict[str, Any]]
    count: int
    source: Literal["hubspot"] = "hubspot"
    object_type: str


class UpsertResponse(BaseModel):
    record_type: str
    hubspot_object_type: str
    id: str
    created: bool
    properties: dict[str, Any]
    source: Literal["hubspot"] = "hubspot"


class ReadResponse(BaseModel):
    record_type: str
    hubspot_object_type: str
    id: str
    properties: dict[str, Any]
    source: Literal["hubspot"] = "hubspot"
