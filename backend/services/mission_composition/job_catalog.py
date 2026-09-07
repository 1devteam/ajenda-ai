"""Unified business job catalog for mission composition.

Jobs own canonical outcome IDs, typed dependencies, candidate actions, and completion
semantics. Natural-language aliases belong to the interpreter vocabulary only.
Jobs do not execute tools.
"""

from __future__ import annotations

from backend.services.mission_composition.contracts import JOB_CATALOG_VERSION, BusinessJob, JobDependency

SALES_GTM_JOBS: tuple[BusinessJob, ...] = (
    BusinessJob(
        job_key="research.discover_prospects",
        display_name="Discover prospects",
        vertical_role="vertical.research",
        supported_outcomes=("research_prospects",),
        required_inputs=("target_industry_or_query",),
        produced_outputs=("prospect_candidates",),
        candidate_actions=("web.research", "web.search", "web.page_read", "sales.research", "crm.research"),
        risk_level="low",
        maturity="runtime_bound",
        credential_policy="optional",
        evidence_requirements=("action_result_evidence",),
        seed_brain_missions=("M3", "M10"),
    ),
    BusinessJob(
        job_key="research.observe_sources",
        display_name="Observe contacts from sources",
        vertical_role="vertical.research",
        supported_outcomes=("observe_contacts",),
        required_inputs=("prospect_candidates",),
        produced_outputs=("observed_contacts",),
        candidate_actions=("research.observe_contacts",),
        risk_level="low",
        maturity="runtime_bound",
        credential_policy="none",
        evidence_requirements=("action_result_evidence",),
        dependencies=(
            JobDependency(
                job_key="research.discover_prospects",
                kind="conditional",
                required_when_missing=("prospect_candidates",),
                satisfied_by=("explicit_company", "crm_record", "prior_artifact"),
            ),
        ),
        depends_on_jobs=(),
    ),
    BusinessJob(
        job_key="research.synthesize_report",
        display_name="Synthesize research report",
        vertical_role="vertical.research",
        supported_outcomes=("synthesize_research_report",),
        required_inputs=("prospect_candidates",),
        produced_outputs=("research_report",),
        candidate_actions=("research.synthesize_report",),
        risk_level="low",
        maturity="runtime_bound",
        credential_policy="none",
        evidence_requirements=("action_result_evidence",),
        dependencies=(JobDependency(job_key="research.discover_prospects", kind="hard"),),
        depends_on_jobs=("research.discover_prospects",),
    ),
    BusinessJob(
        job_key="operations.verify_runtime_controls",
        display_name="Verify runtime controls",
        vertical_role="vertical.operations",
        supported_outcomes=("verify_runtime_controls",),
        required_inputs=(),
        produced_outputs=("runtime_control_verification_package",),
        candidate_actions=("runtime.verify_controls",),
        risk_level="low",
        maturity="runtime_bound",
        credential_policy="none",
        evidence_requirements=("action_result_evidence",),
    ),
    BusinessJob(
        job_key="intelligence.retrieve_knowledge",
        display_name="Retrieve current knowledge",
        vertical_role="vertical.research",
        # Optional decision support is planner/know-how selectable, not a
        # deterministic requirement of the observe_contacts outcome.
        supported_outcomes=(),
        # knowledge.retrieve_current builds a semantic query from MissionIntent;
        # it does not consume the concrete observed_contacts runtime artifact.
        required_inputs=(),
        produced_outputs=("retrieved_knowledge",),
        candidate_actions=("knowledge.retrieve_current",),
        risk_level="low",
        maturity="runtime_bound",
        credential_policy="none",
        evidence_requirements=("action_result_evidence",),
        dependencies=(
            JobDependency(
                job_key="research.observe_sources",
                kind="hard",
            ),
        ),
        depends_on_jobs=(),
    ),
    BusinessJob(
        job_key="intelligence.retrieve_business_profile",
        display_name="Read approved business profile",
        vertical_role="vertical.research",
        supported_outcomes=("read_business_profile",),
        required_inputs=("profile_query",),
        produced_outputs=("business_profile_facts",),
        candidate_actions=("retrieval.hybrid_search",),
        risk_level="low",
        maturity="runtime_bound",
        credential_policy="none",
        evidence_requirements=("action_result_evidence",),
    ),
    BusinessJob(
        job_key="intelligence.advise_next",
        display_name="Recommend next action",
        vertical_role="vertical.research",
        # The governed RevOps know-how owns this as optional decision support.
        supported_outcomes=(),
        required_inputs=("observed_contacts",),
        produced_outputs=("recommendation",),
        candidate_actions=("decision.recommend_next_action",),
        risk_level="low",
        maturity="runtime_bound",
        credential_policy="none",
        evidence_requirements=("action_result_evidence",),
        dependencies=(
            JobDependency(
                job_key="research.observe_sources",
                kind="hard",
            ),
            JobDependency(
                job_key="intelligence.retrieve_knowledge",
                kind="optional",
            ),
        ),
        depends_on_jobs=(),
    ),
    BusinessJob(
        job_key="sales.research_context",
        display_name="Research against business context",
        vertical_role="vertical.sales",
        supported_outcomes=(),
        required_inputs=("prospect_candidates",),
        produced_outputs=("researched_prospects",),
        candidate_actions=("sales.research", "crm.research"),
        risk_level="low",
        maturity="runtime_bound",
        credential_policy="optional",
        evidence_requirements=("action_result_evidence",),
        # Only expand when prospect candidates are not already available.
        dependencies=(
            JobDependency(
                job_key="research.discover_prospects",
                kind="conditional",
                required_when_missing=("prospect_candidates", "recipient_context"),
                satisfied_by=("explicit_recipient", "crm_record", "prior_artifact"),
            ),
        ),
        depends_on_jobs=(),
        seed_brain_missions=("M10",),
    ),
    BusinessJob(
        job_key="sales.qualify_prospects",
        display_name="Qualify prospects",
        vertical_role="vertical.sales",
        supported_outcomes=("qualify_prospects",),
        required_inputs=("prospect_candidates", "observed_contacts"),
        produced_outputs=("qualified_prospects",),
        candidate_actions=("sales.qualify", "sales.score_lead"),
        risk_level="low",
        maturity="runtime_bound",
        credential_policy="none",
        evidence_requirements=("action_result_evidence",),
        dependencies=(
            JobDependency(
                job_key="research.discover_prospects",
                kind="conditional",
                required_when_missing=("prospect_candidates",),
                satisfied_by=("explicit_company", "crm_record", "prior_artifact"),
            ),
            JobDependency(
                job_key="research.observe_sources",
                kind="conditional",
                required_when_missing=("observed_contacts",),
                satisfied_by=("explicit_email", "crm_record"),
            ),
        ),
        depends_on_jobs=(),
        seed_brain_missions=("M4", "M5"),
    ),
    BusinessJob(
        job_key="gtm.enrich_contacts",
        display_name="Enrich selected prospects",
        vertical_role="vertical.sales",
        supported_outcomes=("enrich_contacts",),
        required_inputs=("qualified_prospects", "prospect_candidates"),
        produced_outputs=("enriched_prospects",),
        candidate_actions=("gtm.lead_enrich",),
        risk_level="low",
        maturity="runtime_bound",
        credential_policy="none",
        evidence_requirements=("action_result_evidence",),
        dependencies=(
            JobDependency(
                job_key="sales.qualify_prospects",
                kind="conditional",
                required_when_missing=("qualified_prospects",),
                satisfied_by=("prospect_candidates", "explicit_company"),
            ),
        ),
        depends_on_jobs=(),
        seed_brain_missions=("M6",),
    ),
    BusinessJob(
        job_key="email.prepare_outreach",
        display_name="Prepare outreach drafts",
        vertical_role="vertical.email",
        supported_outcomes=("prepare_outreach",),
        required_inputs=("recipient_context",),
        produced_outputs=("introduction_drafts",),
        candidate_actions=("gtm.email_draft", "sales.draft_followup"),
        risk_level="low",
        maturity="runtime_bound",
        credential_policy="none",
        approval_policy="review_before_external",
        evidence_requirements=("action_result_evidence", "draft_artifact"),
        # Expand discovery/enrich only when recipient context is missing.
        dependencies=(
            JobDependency(
                job_key="gtm.enrich_contacts",
                kind="conditional",
                required_when_missing=("recipient_context", "enriched_prospects"),
                satisfied_by=("explicit_recipient", "explicit_email", "crm_record"),
            ),
            JobDependency(
                job_key="sales.qualify_prospects",
                kind="conditional",
                required_when_missing=("recipient_context", "qualified_prospects"),
                satisfied_by=("explicit_recipient", "explicit_email", "crm_record"),
            ),
            JobDependency(
                job_key="research.discover_prospects",
                kind="conditional",
                required_when_missing=("recipient_context", "prospect_candidates"),
                satisfied_by=("explicit_recipient", "explicit_email", "crm_record", "explicit_company"),
            ),
        ),
        depends_on_jobs=(),
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
        dependencies=(
            JobDependency(
                job_key="email.prepare_outreach",
                kind="hard",
            ),
        ),
        depends_on_jobs=("email.prepare_outreach",),
        seed_brain_missions=("M11",),
    ),
    BusinessJob(
        job_key="email.read_messages",
        display_name="Read Gmail messages",
        vertical_role="vertical.email",
        supported_outcomes=("read_email",),
        required_inputs=("email_query",),
        produced_outputs=("email_messages",),
        candidate_actions=("gtm.email_check",),
        risk_level="medium",
        maturity="runtime_bound",
        credential_policy="required",
        evidence_requirements=("action_result_evidence",),
    ),
    BusinessJob(
        job_key="crm.read_records",
        display_name="Read HubSpot CRM records",
        vertical_role="vertical.sales",
        supported_outcomes=("read_crm",),
        required_inputs=("crm_query",),
        produced_outputs=("crm_records",),
        candidate_actions=("sales.research",),
        risk_level="medium",
        maturity="runtime_bound",
        credential_policy="required",
        evidence_requirements=("action_result_evidence",),
    ),
    BusinessJob(
        job_key="crm.query_salesforce",
        display_name="Query Salesforce records",
        vertical_role="vertical.sales",
        supported_outcomes=("query_salesforce",),
        required_inputs=("soql_query",),
        produced_outputs=("salesforce_records",),
        candidate_actions=("salesforce.soql_read",),
        risk_level="medium",
        maturity="runtime_bound",
        credential_policy="required",
        evidence_requirements=("action_result_evidence",),
    ),
    BusinessJob(
        job_key="crm.internal_persistence",
        display_name="Persist prospects to Ajenda internal CRM",
        vertical_role="vertical.sales",
        supported_outcomes=("persist_internal_crm",),
        required_inputs=("qualified_prospects", "observed_contacts"),
        produced_outputs=("internal_crm_records",),
        candidate_actions=("record.write",),
        risk_level="medium",
        maturity="runtime_bound",
        credential_policy="none",
        evidence_requirements=("action_result_evidence", "readback_evidence"),
        dependencies=(
            JobDependency(job_key="research.discover_prospects", kind="hard"),
            JobDependency(job_key="research.observe_sources", kind="hard"),
            JobDependency(job_key="sales.qualify_prospects", kind="hard"),
        ),
        depends_on_jobs=("research.discover_prospects", "research.observe_sources", "sales.qualify_prospects"),
    ),
    BusinessJob(
        job_key="crm.pipeline_maintenance",
        display_name="Pipeline maintenance",
        vertical_role="vertical.sales",
        supported_outcomes=("update_crm",),
        required_inputs=("qualified_prospects",),
        produced_outputs=("pipeline_records",),
        # CRM-update outcomes require the connector-bound upsert. A local aggregate
        # record cannot truthfully represent per-prospect CRM persistence.
        candidate_actions=("gtm.crm_upsert",),
        risk_level="medium",
        maturity="runtime_bound",
        credential_policy="required",
        evidence_requirements=("action_result_evidence",),
        dependencies=(
            JobDependency(
                job_key="research.discover_prospects",
                kind="conditional",
                required_when_missing=("qualified_prospects",),
                # Industry/location market labels are not concrete CRM records.
                # Only an explicit company name or existing CRM id satisfies without discovery.
                satisfied_by=("named_company", "crm_record"),
            ),
            JobDependency(
                job_key="sales.qualify_prospects",
                kind="conditional",
                required_when_missing=("qualified_prospects",),
                satisfied_by=("named_company", "crm_record", "prospect_candidates", "observed_contacts"),
            ),
            JobDependency(
                job_key="research.observe_sources",
                kind="conditional",
                required_when_missing=("observed_contacts",),
                satisfied_by=("explicit_email", "crm_record"),
            ),
        ),
        depends_on_jobs=(),
        seed_brain_missions=("M9",),
    ),
    BusinessJob(
        job_key="ops.calendar_briefing",
        display_name="Calendar briefing",
        vertical_role="vertical.planning",
        supported_outcomes=("read_calendar",),
        required_inputs=(),
        produced_outputs=("calendar_events",),
        # Google is the real path; local calendar.read is proof-only and not preferred.
        candidate_actions=("google_calendar.events_read",),
        risk_level="low",
        maturity="runtime_bound",
        credential_policy="required",
        evidence_requirements=("action_result_evidence",),
    ),
    BusinessJob(
        job_key="ops.linkedin_profile_read",
        display_name="Read LinkedIn profile",
        vertical_role="vertical.ops",
        supported_outcomes=("read_linkedin",),
        required_inputs=(),
        produced_outputs=("linkedin_profile",),
        candidate_actions=("linkedin.profile_read",),
        risk_level="medium",
        maturity="runtime_bound",
        credential_policy="required",
        evidence_requirements=("action_result_evidence",),
    ),
    BusinessJob(
        job_key="ops.github_repo_read",
        display_name="Read GitHub repository",
        vertical_role="vertical.ops",
        supported_outcomes=("read_github",),
        required_inputs=("github_owner_repo",),
        produced_outputs=("github_repo_metadata",),
        candidate_actions=("github.repo_read",),
        risk_level="medium",
        maturity="runtime_bound",
        credential_policy="required",
        evidence_requirements=("action_result_evidence",),
    ),
    BusinessJob(
        job_key="ops.google_contacts_read",
        display_name="Read Google Contacts",
        vertical_role="vertical.ops",
        supported_outcomes=("read_contacts",),
        required_inputs=(),
        produced_outputs=("contact_records",),
        # Runtime path is provider.external_read against People API (see connector_capabilities).
        candidate_actions=("provider.external_read",),
        risk_level="medium",
        maturity="runtime_bound",
        credential_policy="required",
        evidence_requirements=("action_result_evidence",),
    ),
    # Publish is fully job-bound with external-publish side effects (not stranded).
    BusinessJob(
        job_key="gtm.publish_content",
        display_name="Publish social content",
        vertical_role="vertical.gtm",
        supported_outcomes=("publish_content",),
        required_inputs=("publish_payload",),
        produced_outputs=("published_content",),
        candidate_actions=("gtm.social_publish",),
        risk_level="high",
        maturity="runtime_bound",
        credential_policy="required",
        approval_policy="always_review",
        evidence_requirements=("action_result_evidence",),
        # "Post the results" expands research; standalone post copy does not.
        dependencies=(
            JobDependency(
                job_key="research.discover_prospects",
                kind="conditional",
                required_when_missing=("publish_payload", "standalone_publish_content"),
                satisfied_by=("standalone_publish_content",),
            ),
        ),
        depends_on_jobs=(),
    ),
)

ACCOUNTING_JOBS: tuple[BusinessJob, ...] = (
    BusinessJob(
        job_key="accounting.read_revenue",
        display_name="Read revenue information",
        vertical_role="vertical.finance",
        supported_outcomes=("read_revenue",),
        required_inputs=(),
        produced_outputs=("revenue_records",),
        candidate_actions=("vertical.finance.sync_revenue",),
        risk_level="medium",
        maturity="runtime_bound",
        credential_policy="optional",
        evidence_requirements=("action_result_evidence",),
    ),
    BusinessJob(
        job_key="accounting.prepare_reconciliation",
        display_name="Prepare reconciliation",
        vertical_role="vertical.finance",
        supported_outcomes=("prepare_reconciliation",),
        required_inputs=("revenue_records",),
        produced_outputs=("reconciliation_package",),
        candidate_actions=("vertical.finance.prepare_reconciliation",),
        risk_level="medium",
        maturity="runtime_bound",
        credential_policy="optional",
        evidence_requirements=("document_artifact",),
        dependencies=(JobDependency(job_key="accounting.read_revenue", kind="hard"),),
        depends_on_jobs=("accounting.read_revenue",),
    ),
    BusinessJob(
        job_key="accounting.prepare_invoice_drafts",
        display_name="Prepare invoice drafts",
        vertical_role="vertical.finance",
        supported_outcomes=("prepare_invoice_drafts",),
        required_inputs=("revenue_records",),
        produced_outputs=("invoice_drafts",),
        candidate_actions=("vertical.finance.prepare_invoice_drafts",),
        risk_level="medium",
        maturity="runtime_bound",
        credential_policy="none",
        evidence_requirements=("document_artifact",),
        dependencies=(JobDependency(job_key="accounting.read_revenue", kind="hard"),),
        depends_on_jobs=("accounting.read_revenue",),
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
