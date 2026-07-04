export type ApprovalMode = "notify_before_external" | "always_notify" | "none";

export type OperatingCharter = {
  schema_version: 1;
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
  may_prepare: [
    "retrieval.hybrid_search",
    "record.search",
    "record.read",
    "web.research",
    "web.search",
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
    "gtm.email_check",
    "google_calendar.events_read",
    "calendar.read",
  ],
  may_perform: [
    "gtm.crm_upsert",
    "record.write",
    "sales.log_activity",
    "sales.create_followup_task",
    "calendar.create_event",
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
  { action: "gtm.email_check", label: "Check inbox (Gmail)" },
  { action: "google_calendar.events_read", label: "Google Calendar read" },
  { action: "calendar.read", label: "Local calendar read proof" },
] as const;

export const PERFORM_ACTION_OPTIONS = [
  { action: "gtm.email_send", label: "Send external email (opt-in)" },
  { action: "gtm.crm_upsert", label: "Internal / CRM upsert" },
  { action: "record.write", label: "Internal record write" },
  { action: "sales.log_activity", label: "Log sales activity" },
  { action: "sales.create_followup_task", label: "Create follow-up task" },
  { action: "calendar.create_event", label: "Create calendar event" },
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
  const mayPrepare = "may_prepare" in payload ? payload.may_prepare : DEFAULT_OPERATING_CHARTER.may_prepare;
  const mayPerform = "may_perform" in payload ? payload.may_perform : DEFAULT_OPERATING_CHARTER.may_perform;
  const neverDo = "never_do" in payload ? payload.never_do : DEFAULT_OPERATING_CHARTER.never_do;
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
  return {
    schema_version: 1,
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

export function charterFromProfile(facts: Record<string, unknown>): OperatingCharter {
  return charterPayloadFromFact(facts[CHARTER_CATEGORY]) ?? DEFAULT_OPERATING_CHARTER;
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