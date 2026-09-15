"""Slice 2: GTM and vertical are packs, not kernel.

Kernel CRM writes Ajenda Records. crm_actions must not import vertical_ops.
Default catalog jobs are kernel except GTM pack jobs and finance vertical.
"""

from __future__ import annotations

from pathlib import Path

from backend.app.config import Settings
from backend.services.mission_composition.capability_resolver import resolve_jobs, route_jobs_for_intent
from backend.services.mission_composition.intent_interpreter import interpret_instruction
from backend.services.mission_composition.job_catalog import BUSINESS_JOB_CATALOG, get_business_job
from backend.services.operating_charter import default_operating_charter

REPO_ROOT = Path(__file__).resolve().parents[3]
CRM_ACTIONS = REPO_ROOT / "backend" / "services" / "tools" / "crm_actions.py"

GTM_PACK_JOBS = frozenset(
    {
        "email.prepare_outreach",
        "email.deliver_outreach",
        "email.read_messages",
        "gtm.publish_content",
    }
)
FINANCE_VERTICAL_JOBS = frozenset(
    {
        "accounting.read_revenue",
        "accounting.prepare_reconciliation",
        "accounting.prepare_invoice_drafts",
    }
)


def test_vertical_ops_pack_defaults_off() -> None:
    assert Settings.model_fields["vertical_ops_enabled"].default is False


def test_crm_actions_does_not_import_vertical_ops() -> None:
    source = CRM_ACTIONS.read_text(encoding="utf-8")
    assert "backend.services.vertical_ops" not in source
    assert "backend.services.records" in source


def test_kernel_jobs_are_labeled_kernel() -> None:
    for job in BUSINESS_JOB_CATALOG:
        if job.job_key in GTM_PACK_JOBS:
            assert job.vertical_role == "pack.gtm", job.job_key
        elif job.job_key in FINANCE_VERTICAL_JOBS:
            assert job.vertical_role == "vertical.finance", job.job_key
        else:
            assert job.vertical_role == "kernel", job.job_key


def test_persist_contacts_composition_uses_kernel_record_write() -> None:
    intent = interpret_instruction("Find three roofing companies in Austin and add them to contacts")
    jobs = route_jobs_for_intent(intent)
    selections, missing = resolve_jobs(jobs, intent=intent, charter=default_operating_charter())
    crm = next(item for item in selections if item.job_key == "crm.pipeline_maintenance")

    assert crm.action_name == "record.write"
    assert crm.readiness == "ready"
    assert get_business_job("crm.pipeline_maintenance").vertical_role == "kernel"
    assert get_business_job("crm.internal_persistence").vertical_role == "kernel"
    assert not any(item.get("provider") == "hubspot" for item in missing)


def test_gtm_publish_content_remains_pack_gtm() -> None:
    job = get_business_job("gtm.publish_content")
    assert job.vertical_role == "pack.gtm"
    assert "gtm.social_publish" in job.candidate_actions
