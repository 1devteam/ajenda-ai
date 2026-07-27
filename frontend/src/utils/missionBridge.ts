import { MISSION_ABILITY_PRESETS } from "../config/missionAbilities";
import type { MissionPlanCreateRequest } from "../types";

function presetForAction(action: string) {
  return MISSION_ABILITY_PRESETS.find((item) => item.action === action);
}

/**
 * Seed tool inputs from mission objective — never Example Roofing / @example.com demo stubs.
 * Runtime binder fills prospects from upstream ability outputs.
 */
export function seedToolInputForAction(
  action: string,
  objective: string,
): Record<string, unknown> {
  const objectiveText = objective.trim().slice(0, 400) || "mission outcome";
  const context = {
    objective: objectiveText.slice(0, 300),
    binding_required: true,
    seed_source: "mission_dispatch_ui",
  };

  switch (action) {
    case "web.research":
      return {
        query: objectiveText,
        include_public_search: true,
        fetch_public_page: false,
        limit: 5,
      };
    case "web.search":
      return { query: objectiveText, limit: 5 };
    case "web.page_read":
      return { url: "https://example.com", timeout_seconds: 8 };
    case "web.browser_session":
      return { url: "https://example.com", timeout_seconds: 15, wait_until: "domcontentloaded" };
    case "web.open_write":
      return {
        url: "https://httpbin.org/post",
        method: "POST",
        json_body: { objective: objectiveText.slice(0, 200) },
        idempotency_key: `mission-open-write-${Date.now()}`,
        timeout_seconds: 10,
      };
    case "http.request":
      return { method: "GET", url: "https://example.com", timeout_seconds: 5 };
    case "sales.qualify":
    case "sales.score_lead":
      return {
        lead: { company: "pending upstream prospect", source: "mission_dispatch" },
        prospects: [],
        context,
      };
    case "gtm.lead_enrich":
      return {
        company: "pending upstream prospect",
        prospects: [],
        context,
      };
    case "gtm.email_draft":
      return {
        recipient: "pending.binding@invalid.local",
        topic: "Introduction",
        tone: "professional",
        prospects: [],
        context: {
          ...context,
          binding_source: "upstream_enriched_prospects",
          compose_note:
            "Recipient stays non-deliverable until enrich yields a real contact email.",
        },
      };
    case "sales.draft_followup":
      return {
        recipient_name: "Prospect (pending enrichment)",
        topic: "Follow-up",
        tone: "professional",
        context,
      };
    case "gtm.email_send":
      return {
        to: "pending.binding@invalid.local",
        subject: "Introduction",
        body: "Prepared by mission dispatch; requires bound recipient and human review before send.",
        context: {
          ...context,
          binding_source: "upstream_introduction_drafts",
        },
      };
    case "sales.research":
    case "crm.research":
      return {
        lead: { company: objectiveText.slice(0, 120), source: "mission_dispatch" },
        context,
      };
    case "gtm.email_check":
      return { query: "in:inbox", limit: 5 };
    default: {
      const preset = presetForAction(action);
      // Prefer empty/objective context over demo company emails in presets.
      if (preset?.input && typeof preset.input === "object") {
        const clone = { ...preset.input } as Record<string, unknown>;
        if (typeof clone.query === "string" && objectiveText) {
          clone.query = objectiveText;
        }
        return clone;
      }
      return { context: { objective: objectiveText.slice(0, 300) } };
    }
  }
}

export function buildMissionPlanPayload(
  objective: string,
  allowedActions: string[],
  successCriteria: string[] = [],
): MissionPlanCreateRequest {
  const steps = allowedActions.map((action, index) => {
    const preset = presetForAction(action);
    return {
      sequence: index + 1,
      title: preset?.title ?? action,
      description: preset?.description ?? `Execute ${action} as part of the mission outcome.`,
      depends_on: index > 0 ? [index] : [],
      expected_output: `${action} artifacts`,
      metadata: { action },
    };
  });

  return {
    objectives: [objective],
    constraints: ["Operate only within mission allowed_actions scope."],
    assumptions: ["Tenant credentials are configured for external abilities when required."],
    acceptance_criteria:
      successCriteria.length > 0 ? successCriteria : ["Each planned ability step produces governed evidence."],
    planned_steps:
      steps.length > 0
        ? steps
        : [
            {
              sequence: 1,
              title: "Execute mission outcome",
              description: "Run governed abilities scoped to this mission.",
              depends_on: [],
              expected_output: "Mission deliverables",
              metadata: {},
            },
          ],
    risk_notes: ["External side effects require explicit runtime authority and credentials."],
  };
}

// Client graph / materialization / admission invent removed.
// Authority path: POST /v1/missions/{id}/compile → runtime-admission (server-derived nodes).

export const PIPELINE_STEPS = [
  { id: "plan", label: "Mission plan", completenessKey: "has_plan" as const },
  { id: "graph", label: "Task graph", completenessKey: "has_task_graph" as const },
  { id: "materialize", label: "Graph materialization", completenessKey: "has_materialization" as const },
  { id: "authority", label: "Runtime authority", completenessKey: null },
  { id: "admit", label: "Runtime admission", completenessKey: "has_runtime_admission" as const },
  { id: "readiness", label: "Runtime readiness", completenessKey: null },
  { id: "tasks", label: "Task materialization", completenessKey: null },
  { id: "queue", label: "Queue admission", completenessKey: null },
] as const;

/** Read allowed actions from mission intake metadata (composition or legacy). */
export function intakeAllowedActions(intake: Record<string, unknown> | null): string[] {
  if (!intake) {
    return [];
  }
  const raw = intake.allowed_actions;
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
}

/** Read success criteria descriptions from mission intake metadata. */
export function intakeSuccessCriteria(intake: Record<string, unknown> | null): string[] {
  if (!intake) {
    return [];
  }
  const raw = intake.success_criteria;
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw
    .map((item) => {
      if (typeof item === "object" && item !== null && "description" in item) {
        const description = (item as { description: unknown }).description;
        return typeof description === "string" ? description.trim() : "";
      }
      return "";
    })
    .filter((item) => item.length > 0);
}
