"""Unified business job catalog for mission composition.

Jobs own canonical outcome IDs, dependencies, candidate actions, and completion
semantics. Natural-language aliases belong to the interpreter vocabulary only.
Jobs do not execute tools.
"""

from __future__ import annotations

from backend.services.mission_composition.contracts import JOB_CATALOG_VERSION, BusinessJob

# Sales/GTM runtime-bound jobs used by the flagship composition proof.
SALES_GTM_JOBS: tuple[BusinessJob, ...] = (
    BusinessJob(
        job_key="research.discover_prospects",
        display_name="Discover prospects",
        vertical_role="vertical.research",
        supported_outcomes=("research_prospects",),
        required_inputs=("target_industry_or_query",),
        produced_outputs=("prospect_candidates",),
        candidate_actions=("web.research", "web.search", "sales.research", "crm.research"),
        risk_level="low",
        maturity="runtime_bound",
        credential_policy="optional",
        evidence_requirements=("action_result_evidence",),
        seed_brain_missions=("M3", "M10"),
    ),
    BusinessJob(
        job_key="sales.research_context",
        display_name="Research against business context",
        vertical_role="vertical.sales",
        # Secondary research against existing records — not primary discovery.
        supported_outcomes=(),
        required_inputs=("prospect_candidates",),
        produced_outputs=("researched_prospects",),
        candidate_actions=("sales.research", "crm.research", "web.research"),
        risk_level="low",
        maturity="runtime_bound",
        credential_policy="optional",
        evidence_requirements=("action_result_evidence",),
        depends_on_jobs=("research.discover_prospects",),
        seed_brain_missions=("M10",),
    ),
    BusinessJob(
        job_key="sales.qualify_prospects",
        display_name="Qualify prospects",
        vertical_role="vertical.sales",
        supported_outcomes=("qualify_prospects",),
        required_inputs=("researched_prospects", "prospect_candidates"),
        produced_outputs=("qualified_prospects",),
        candidate_actions=("sales.qualify", "sales.score_lead"),
        risk_level="low",
        maturity="runtime_bound",
        credential_policy="none",
        evidence_requirements=("action_result_evidence",),
        depends_on_jobs=("research.discover_prospects",),
        seed_brain_missions=("M4", "M5"),
    ),
    BusinessJob(
        job_key="gtm.enrich_contacts",
        display_name="Enrich selected prospects",
        vertical_role="vertical.sales",
        supported_outcomes=("enrich_contacts",),
        required_inputs=("qualified_prospects",),
        produced_outputs=("enriched_prospects",),
        candidate_actions=("gtm.lead_enrich",),
        risk_level="low",
        maturity="runtime_bound",
        credential_policy="none",
        evidence_requirements=("action_result_evidence",),
        depends_on_jobs=("sales.qualify_prospects",),
        seed_brain_missions=("M6",),
    ),
    BusinessJob(
        job_key="email.prepare_outreach",
        display_name="Prepare outreach drafts",
        vertical_role="vertical.email",
        supported_outcomes=("prepare_outreach",),
        required_inputs=("enriched_prospects", "qualified_prospects"),
        produced_outputs=("introduction_drafts",),
        candidate_actions=("gtm.email_draft", "sales.draft_followup"),
        risk_level="low",
        maturity="runtime_bound",
        credential_policy="none",
        approval_policy="review_before_external",
        evidence_requirements=("action_result_evidence", "draft_artifact"),
        depends_on_jobs=("gtm.enrich_contacts", "sales.qualify_prospects"),
        seed_brain_missions=("M7", "M8"),
    ),
    BusinessJob(
        job_key="email.deliver_outreach",
        display_name="Deliver outreach",
        vertical_role="vertical.email",
        supported_outcomes=("send_outreach",),
        required_inputs=("introduction_drafts",),
        produced_outputs=("sent_messages",),
        candidate_actions=("gtm.email_send",),
        risk_level="high",
        maturity="runtime_bound",
        credential_policy="required",
        approval_policy="always_review",
        evidence_requirements=("action_result_evidence",),
        depends_on_jobs=("email.prepare_outreach",),
        seed_brain_missions=("M11",),
    ),
    BusinessJob(
        job_key="crm.pipeline_maintenance",
        display_name="Pipeline maintenance",
        vertical_role="vertical.sales",
        supported_outcomes=("update_crm",),
        required_inputs=("qualified_prospects",),
        produced_outputs=("pipeline_records",),
        candidate_actions=("gtm.crm_upsert", "sales.log_activity", "record.write"),
        risk_level="medium",
        maturity="runtime_bound",
        credential_policy="optional",
        evidence_requirements=("action_result_evidence",),
        seed_brain_missions=("M9",),
    ),
    BusinessJob(
        job_key="ops.calendar_briefing",
        display_name="Calendar briefing",
        vertical_role="vertical.planning",
        supported_outcomes=("read_calendar",),
        required_inputs=(),
        produced_outputs=("calendar_events",),
        candidate_actions=("google_calendar.events_read", "calendar.read"),
        risk_level="low",
        maturity="runtime_bound",
        credential_policy="optional",
        evidence_requirements=("action_result_evidence",),
    ),
)

# Accounting jobs are structural only — catalog_only until providers exist.
# Outcome IDs reserved for future interpreter vocabulary; not user-mapped yet.
ACCOUNTING_JOBS: tuple[BusinessJob, ...] = (
    BusinessJob(
        job_key="accounting.read_revenue",
        display_name="Read revenue information",
        vertical_role="vertical.finance",
        supported_outcomes=(),
        required_inputs=(),
        produced_outputs=("revenue_records",),
        candidate_actions=("vertical.finance.sync_revenue", "record.search"),
        risk_level="medium",
        maturity="catalog_only",
        credential_policy="required",
        evidence_requirements=("action_result_evidence",),
    ),
    BusinessJob(
        job_key="accounting.prepare_reconciliation",
        display_name="Prepare reconciliation",
        vertical_role="vertical.finance",
        supported_outcomes=(),
        required_inputs=("revenue_records",),
        produced_outputs=("reconciliation_package",),
        candidate_actions=("document.generate", "record.search"),
        risk_level="medium",
        maturity="catalog_only",
        credential_policy="optional",
        evidence_requirements=("document_artifact",),
    ),
    BusinessJob(
        job_key="accounting.prepare_invoice_drafts",
        display_name="Prepare invoice drafts",
        vertical_role="vertical.finance",
        supported_outcomes=(),
        required_inputs=("revenue_records",),
        produced_outputs=("invoice_drafts",),
        candidate_actions=("document.generate",),
        risk_level="medium",
        maturity="catalog_only",
        credential_policy="none",
        evidence_requirements=("document_artifact",),
    ),
)

BUSINESS_JOB_CATALOG: tuple[BusinessJob, ...] = SALES_GTM_JOBS + ACCOUNTING_JOBS
BUSINESS_JOBS_BY_KEY: dict[str, BusinessJob] = {job.job_key: job for job in BUSINESS_JOB_CATALOG}


def get_business_job(job_key: str) -> BusinessJob:
    try:
        return BUSINESS_JOBS_BY_KEY[job_key]
    except KeyError as exc:
        raise ValueError(f"unknown business job_key: {job_key}") from exc


def list_business_jobs(*, maturity: str | None = None) -> tuple[BusinessJob, ...]:
    if maturity is None:
        return BUSINESS_JOB_CATALOG
    return tuple(job for job in BUSINESS_JOB_CATALOG if job.maturity == maturity)


def job_catalog_version() -> str:
    return JOB_CATALOG_VERSION
