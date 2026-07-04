"""Ajenda light CRM — structured internal records, timeline, mission-native workflows."""

from backend.services.light_crm.workflow import (
    on_crm_upsert_completed,
    on_draft_approved,
    on_email_sent,
    workflow_suggestions,
)

__all__ = [
    "on_crm_upsert_completed",
    "on_draft_approved",
    "on_email_sent",
    "workflow_suggestions",
]
