export type ApprovalMode = "notify_before_external" | "always_notify" | "none";

export type OperatingCharter = {
  schema_version: 1;
  revision: number;
  may_prepare: string[];
  may_perform: string[];
  never_do: string[];
  approval_mode: ApprovalMode;
  escalation_email?: string;
  escalation_phone?: string;
};

export const CHARTER_CATEGORY = "operating_charter";

export const DEFAULT_OPERATING_CHARTER: OperatingCharter = {
  schema_version: 1,
  revision: 0,
  may_prepare: [
    "retrieval.hybrid_search",
    "record.search",
    "record.read",
    "web.research",
    "web.search",
    "web.page_read",
    "research.observe_contacts",
    "research.verify_public_candidates",
    "research.verify_public_identity",
    "research.synthesize_report",
    "knowledge.retrieve_current",
    "knowledge.inform_decision",
    "decision.recommend_next_action",
    "web.browser_session",
    "http.request",
    "sales.qualify",
    "sales.score_lead",
    "sales.recommend_next_action",
    "gtm.lead_enrich",
    "gtm.email_draft",
    "sales.draft_followup",
    "document.generate",
    "document.search",
    "document.read",
    "sales.research",
    "crm.research",
    "crm.read",
    "crm.observe",
    "crm.reconcile",
    "crm.verify_effect",
    "salesforce.soql_read",
    "provider.external_read",
    "linkedin.profile_read",
    "github.repo_read",
    "gtm.email_check",
    "google_calendar.events_read",
    "calendar.read",
    "vertical.finance.sync_revenue",
    "vertical.finance.prepare_reconciliation",
    "vertical.finance.prepare_invoice_drafts",
    "runtime.verify_controls",
    "analysis.evaluate_goal_progress",
  ],
  may_perform: [
    "gtm.crm_upsert",
    "record.write",
    "sales.log_activity",
    "sales.create_followup_task",
    "calendar.create_event",
    "web.open_write",
    "crm.mutate",
  ],
  never_do: ["gtm.email_send", "gtm.social_publish", "webhook.dispatch"],
  approval_mode: "notify_before_external",
};

export const PREPARE_ACTION_OPTIONS = [
  { action: "retrieval.hybrid_search", label: "Hybrid memory retrieval" },
  { action: "record.search", label: "Internal record search" },
  { action: "record.read", label: "Read internal record" },
  { action: "web.research", label: "Web research" },
  { action: "web.search", label: "Web search" },
  { action: "web.page_read", label: "Web page read" },
  { action: "research.observe_contacts", label: "Observe contacts from pages" },
  { action: "research.verify_public_candidates", label: "Verify public company candidates" },
  { action: "research.verify_public_identity", label: "Verify public company identity" },
  { action: "research.synthesize_report", label: "Synthesize research report" },
  { action: "knowledge.retrieve_current", label: "Retrieve current knowledge" },
  { action: "knowledge.inform_decision", label: "Apply qualified knowledge to a decision" },
  { action: "decision.recommend_next_action", label: "Recommend next action" },
  { action: "web.browser_session", label: "Web browser session" },
  { action: "http.request", label: "HTTP request" },
  { action: "sales.qualify", label: "Lead qualification" },
  { action: "sales.score_lead", label: "Score lead" },
  { action: "sales.recommend_next_action", label: "Recommend next action" },
  { action: "gtm.lead_enrich", label: "Lead enrich" },
  { action: "gtm.email_draft", label: "Draft email" },
  { action: "sales.draft_followup", label: "Draft follow-up" },
  { action: "document.generate", label: "Generate document artifact" },
  { action: "document.search", label: "Search clerical library" },
  { action: "document.read", label: "Read document artifact" },
  { action: "sales.research", label: "Sales research" },
  { action: "crm.research", label: "CRM research" },
  { action: "crm.read", label: "CRM read" },
  { action: "crm.observe", label: "Observe canonical CRM state" },
  { action: "crm.reconcile", label: "Prepare CRM reconciliation" },
  { action: "crm.verify_effect", label: "Verify CRM effect" },
  { action: "crm.mutate", label: "Mutate internal CRM" },
  { action: "salesforce.soql_read", label: "Salesforce read-only query" },
  { action: "provider.external_read", label: "External provider read" },
  { action: "linkedin.profile_read", label: "LinkedIn profile read" },
  { action: "github.repo_read", label: "GitHub repo read" },
  { action: "gtm.email_check", label: "Check inbox (Gmail)" },
  { action: "google_calendar.events_read", label: "Google Calendar read" },
  { action: "calendar.read", label: "Local calendar read proof" },
  { action: "vertical.finance.sync_revenue", label: "Sync revenue records" },
  { action: "vertical.finance.prepare_reconciliation", label: "Prepare reconciliation" },
  { action: "vertical.finance.prepare_invoice_drafts", label: "Prepare invoice drafts" },
  { action: "runtime.verify_controls", label: "Verify runtime controls" },
  { action: "analysis.evaluate_goal_progress", label: "Evaluate goal progress" },
] as const;

export const PERFORM_ACTION_OPTIONS = [
  { action: "gtm.email_send", label: "Send external email (opt-in)" },
  { action: "gtm.crm_upsert", label: "Internal / CRM upsert" },
  { action: "crm.mutate", label: "Mutate internal CRM" },
  { action: "record.write", label: "Internal record write" },
  { action: "sales.log_activity", label: "Log sales activity" },
  { action: "sales.create_followup_task", label: "Create follow-up task" },
  { action: "calendar.create_event", label: "Create calendar event" },
  { action: "web.open_write", label: "Public web open write (POST/PUT/PATCH)" },
] as const;

export const NEVER_DO_OPTIONS = [
  { action: "gtm.email_send", label: "Send external email" },
  { action: "gtm.social_publish", label: "Publish to social" },
  { action: "webhook.dispatch", label: "Dispatch webhook" },
] as const;

function charterPayloadFromFact(raw: unknown): OperatingCharter | null {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const record = raw as Record<string, unknown>;
  const nested = record.value;
  const payload = nested && typeof nested === "object" ? (nested as Record<string, unknown>) : record;
  const mayPrepare = payload.may_prepare;
  const mayPerform = payload.may_perform;
  const neverDo = payload.never_do;
  if (!Array.isArray(mayPrepare) || !Array.isArray(mayPerform) || !Array.isArray(neverDo)) {
    return null;
  }
  const approvalMode = payload.approval_mode;
  if (
    approvalMode !== "notify_before_external" &&
    approvalMode !== "always_notify" &&
    approvalMode !== "none"
  ) {
    return null;
  }
  if (payload.schema_version !== 1 || !Number.isInteger(payload.revision) || Number(payload.revision) < 0) {
    return null;
  }
  return {
    schema_version: 1,
    revision: Number(payload.revision),
    may_prepare: mayPrepare.map((item) => String(item)),
    may_perform: mayPerform.map((item) => String(item)),
    never_do: neverDo.map((item) => String(item)),
    approval_mode: approvalMode,
    escalation_email:
      typeof payload.escalation_email === "string" ? payload.escalation_email.trim() : undefined,
    escalation_phone:
      typeof payload.escalation_phone === "string" ? payload.escalation_phone.trim() : undefined,
  };
}

/**
 * Parse only the saved effective charter returned by the API.  Callers may
 * choose DEFAULT_OPERATING_CHARTER as an editor draft, but never as proof of
 * runtime authority for an existing tenant.
 */
export function charterFromPersistedProfile(facts: Record<string, unknown>): OperatingCharter | null {
  return charterPayloadFromFact(facts[CHARTER_CATEGORY]);
}

export function charterToFact(charter: OperatingCharter): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    schema_version: charter.schema_version,
    may_prepare: charter.may_prepare,
    may_perform: charter.may_perform,
    never_do: charter.never_do,
    approval_mode: charter.approval_mode,
  };
  if (charter.escalation_email?.trim()) {
    payload.escalation_email = charter.escalation_email.trim();
  }
  if (charter.escalation_phone?.trim()) {
    payload.escalation_phone = charter.escalation_phone.trim();
  }
  return { value: payload };
}

export function toggleActionList(list: string[], action: string, enabled: boolean): string[] {
  if (enabled) {
    return list.includes(action) ? list : [...list, action];
  }
  return list.filter((item) => item !== action);
}

/** Actions that cannot sit in both may_perform and never_do at once. */
const CHARTER_MUTEX_ACTIONS = new Set(["gtm.email_send"]);

export function applyMayPerformToggle(
  charter: OperatingCharter,
  action: string,
  enabled: boolean,
): OperatingCharter {
  const may_perform = toggleActionList(charter.may_perform, action, enabled);
  const never_do =
    enabled && CHARTER_MUTEX_ACTIONS.has(action)
      ? charter.never_do.filter((item) => item !== action)
      : charter.never_do;
  return { ...charter, may_perform, never_do };
}

export function applyNeverDoToggle(
  charter: OperatingCharter,
  action: string,
  enabled: boolean,
): OperatingCharter {
  const never_do = toggleActionList(charter.never_do, action, enabled);
  const may_perform =
    enabled && CHARTER_MUTEX_ACTIONS.has(action)
      ? charter.may_perform.filter((item) => item !== action)
      : charter.may_perform;
  return { ...charter, never_do, may_perform };
}
