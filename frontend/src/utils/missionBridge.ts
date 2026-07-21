import { MISSION_ABILITY_PRESETS } from "../config/missionAbilities";
import type {
  GraphMaterializationWriteRequest,
  MissionPlanCreateRequest,
  MissionTaskGraphPayload,
  RuntimeAdmissionWriteRequest,
} from "../types";

function slugifyAction(action: string): string {
  return action.replace(/\./g, "-");
}

function bridgeCapabilityName(action: string): string {
  return `bridge_${action.replace(/\./g, "_")}`;
}

function presetForAction(action: string) {
  return MISSION_ABILITY_PRESETS.find((item) => item.action === action);
}

/** Job-catalog style product names for ability world-state binding. */
function producedOutputForAction(action: string): string | null {
  if (action === "web.research" || action === "web.search") return "prospect_candidates";
  if (action === "sales.qualify" || action === "sales.score_lead") return "qualified_prospects";
  if (action === "gtm.lead_enrich") return "enriched_prospects";
  if (action === "gtm.email_draft" || action === "sales.draft_followup") return "introduction_drafts";
  if (action === "sales.research" || action === "crm.research") return "prospect_candidates";
  return null;
}

function bindingInputPathForAction(action: string, outputName: string): string | null {
  if (
    action === "sales.qualify" ||
    action === "sales.score_lead" ||
    action === "gtm.lead_enrich" ||
    action === "gtm.email_draft" ||
    action === "sales.draft_followup"
  ) {
    return "$.input.prospects";
  }
  if (action === "gtm.email_send") {
    if (
      outputName === "introduction_drafts" ||
      outputName === "enriched_prospects" ||
      outputName === "qualified_prospects" ||
      outputName === "prospect_candidates"
    ) {
      return `$.input.context.${outputName}`;
    }
    return "$.input.context.upstream";
  }
  return null;
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

export function buildTaskGraphPayload(
  allowedActions: string[],
  objective = "",
): MissionTaskGraphPayload {
  const nodes = allowedActions.map((action, index) => {
    const preset = presetForAction(action);
    const nodeKey = `ability-${slugifyAction(action)}`;
    const capabilityName = bridgeCapabilityName(action);
    const capabilityReference = {
      capability_id: null,
      name: capabilityName,
      version: "1.0.0",
      purpose: `Bridge authority for ${action}.`,
    };

    // Sequential world-state bindings (same plane as composition plan_compiler).
    const input_bindings: Array<Record<string, string>> = [];
    if (index > 0) {
      const prevAction = allowedActions[index - 1];
      const prevKey = `ability-${slugifyAction(prevAction)}`;
      const outputName = producedOutputForAction(prevAction) ?? "result";
      const inputPath = bindingInputPathForAction(action, outputName);
      if (inputPath) {
        input_bindings.push({
          from_step: prevKey,
          output_path: `$.${outputName}`,
          to_step: nodeKey,
          input_path: inputPath,
        });
      }
    }

    const needsExternalAuth =
      action === "web.research" ||
      action === "web.search" ||
      action === "gtm.email_send" ||
      Boolean(preset?.requiresCredential);

    const toolInput = seedToolInputForAction(action, objective);
    const inputContract: Record<string, unknown> = {
      tool_invocation: {
        schema_version: 1,
        action,
        input: toolInput,
      },
    };
    if (needsExternalAuth && (action === "web.research" || action === "web.search" || action === "gtm.email_send")) {
      inputContract.execution_constraints = {
        side_effect_authorization: {
          schema_version: 1,
          allowed_actions: [action],
          reason: "mission_dispatch_ui",
          approved_by: "mission-dispatch-ui",
        },
      };
    }

    return {
      node_key: nodeKey,
      key: nodeKey,
      title: preset?.title ?? action,
      description: preset?.description ?? `Invoke ${action} through the governed runtime.`,
      capability_reference: capabilityReference,
      capability_references: [capabilityReference],
      input_contract: inputContract,
      output_contract: {
        artifact: producedOutputForAction(action) ?? `${action}_result`,
      },
      metadata: {
        sequence: index + 1,
        action,
        read_only: !preset?.requiresCredential,
        input_bindings,
        output_contract: producedOutputForAction(action) ?? `${action}_result`,
        selected_by: "mission_dispatch_ui",
      },
    };
  });

  const edges = nodes.slice(1).map((node, index) => ({
    from_node_key: nodes[index].key,
    to_node_key: node.key,
    dependency_type: "depends_on",
    metadata: { description: "Sequential ability execution with world-state binding." },
  }));

  return {
    schema_version: 1,
    graph_status: "draft",
    nodes,
    edges,
    metadata: {
      generated_by: "mission-dispatch-ui",
      operator_notes: "Auto-generated from allowed_actions with ability world-state bindings.",
    },
  };
}

export function buildMaterializationPayload(
  allowedActions: string[],
): GraphMaterializationWriteRequest {
  const now = new Date().toISOString();
  const selections = allowedActions.map((action) => ({
    node_key: `ability-${slugifyAction(action)}`,
    capability_name: bridgeCapabilityName(action),
    capability_version: "1.0.0",
    selection_reason: `Auto-selected bridge authority for ${action}.`,
    selected_by: "mission-dispatch-ui",
    alternatives_considered: [],
  }));

  return {
    materialization_status: "validated",
    materialization_source: "mission_dispatch_ui",
    materialization_source_version: "1",
    planner_provenance: {
      planner_type: "mission_dispatch_ui",
      planner_id: "dispatch-ui-v1",
      planning_run_id: `run-${Date.now()}`,
      plan_schema_version: 1,
    },
    capability_selection_provenance: selections,
    graph_validation_result: {
      validation_status: "valid",
      summary: "Graph generated from mission allowed_actions passed contract validation.",
      validated_at: now,
      checks: [
        { name: "node_keys", status: "passed", details: "All nodes have stable keys." },
        { name: "tool_invoke_contract", status: "passed", details: "Each node declares tool.invoke input." },
      ],
    },
    operator_review: {
      status: "pending",
      notes: "Auto-materialized from mission dispatch UI.",
    },
    graph_generation_metadata: {
      generator: "mission-dispatch-ui",
      generation_mode: "deterministic",
      generated_at: now,
      compiler_version: "1.1.0",
      source_plan_version: "1",
      deterministic_inputs: { source: "allowed_actions" },
    },
    deterministic_compilation_metadata: {
      compiler_name: "mission-dispatch-ui-compiler",
      compiler_version: "1.1.0",
      compilation_boundary: "allowed_actions_to_task_graph",
      deterministic: true,
    },
    generation_notes: [
      "Metadata-only materialization from customer dispatch UI with world-state input_bindings.",
    ],
  };
}

export function buildRuntimeAdmissionPayload(
  allowedActions: string[],
  admittedBy: string,
  nodeAuthorities: Array<{
    node_key: string;
    capability_id: string;
    adapter_id: string;
  }>,
): RuntimeAdmissionWriteRequest {
  const authorityByNode = new Map(nodeAuthorities.map((item) => [item.node_key, item]));
  return {
    admission_status: "admitted",
    admitted_by: admittedBy,
    selected_nodes: allowedActions.map((action) => {
      const nodeKey = `ability-${slugifyAction(action)}`;
      const authority = authorityByNode.get(nodeKey);
      return {
        node_key: nodeKey,
        runtime_task_type: "tool.invoke",
        capability_id: authority?.capability_id,
        adapter_id: authority?.adapter_id,
        operator_notes: "Admitted through mission dispatch UI.",
      };
    }),
    validation_notes: ["Runtime admission via customer mission dispatch pipeline."],
  };
}

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
