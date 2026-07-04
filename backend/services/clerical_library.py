"""Seed and query the tenant clerical document library."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.services.document_artifacts import persist_artifact

DEMO_CAPABILITY_RESUME_ID = "capability_resume-ajenda-core"
DEMO_ROI_BRIEF_ID = "roi_brief-ajenda-pilot"


def clerical_library_seed_documents() -> tuple[dict[str, Any], dict[str, Any]]:
    capability_resume = {
        "artifact_type": "capability_resume",
        "review_status": "approved",
        "content": {
            "title": "Ajenda AI — Governed clerical worker",
            "body": (
                "Ajenda runs mission-scoped abilities with leases, evidence, and charter gates. "
                "Prepare paths cover hybrid retrieval, web research, and LLM drafts. "
                "Perform paths cover internal CRM writes and optional platform email send after review."
            ),
            "generation_mode": "library_seed",
        },
        "metadata": {
            "source": "clerical_library",
            "topic": "Ajenda capability overview",
            "library": True,
        },
    }
    roi_brief = {
        "artifact_type": "roi_brief",
        "review_status": "approved",
        "content": {
            "title": "ROI brief — clerical automation pilot",
            "body": (
                "Pilot teams replace ad-hoc AI scripts with one governed brain. "
                "Expected wins: faster follow-ups, audit-ready evidence, fewer credential sprawl incidents. "
                "Measure time-to-first-governed-send and operator review throughput."
            ),
            "generation_mode": "library_seed",
        },
        "metadata": {
            "source": "clerical_library",
            "topic": "Pilot ROI framing",
            "library": True,
        },
    }
    return capability_resume, roi_brief


def seed_clerical_library(*, session: Session, tenant_id: str) -> list[str]:
    capability_resume, roi_brief = clerical_library_seed_documents()
    saved_ids: list[str] = []
    for artifact_id, payload in (
        (DEMO_CAPABILITY_RESUME_ID, capability_resume),
        (DEMO_ROI_BRIEF_ID, roi_brief),
    ):
        persist_artifact(
            session,
            tenant_id=tenant_id,
            artifact_type=str(payload["artifact_type"]),
            content=dict(payload["content"]),
            metadata=dict(payload["metadata"]),
            artifact_id=artifact_id,
            review_status=str(payload["review_status"]),  # type: ignore[arg-type]
        )
        saved_ids.append(artifact_id)
    return saved_ids
