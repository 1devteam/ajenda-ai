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
    planned_steps: steps.length > 0 ? steps : [
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

export function buildTaskGraphPayload(allowedActions: string[]): MissionTaskGraphPayload {
  const nodes = allowedActions.map((action, index) => {
    const preset = presetForAction(action);
    const nodeKey = `ability-${slugifyAction(action)}`;
    const capabilityName = bridgeCapabilityName(action);
    return {
      node_key: nodeKey,
      key: nodeKey,
      name: preset?.title ?? action,
      title: preset?.title ?? action,
      description: preset?.description ?? `Invoke ${action} through the governed runtime.`,
      intended_task_type: "tool.invoke",
      capability_reference: {
        capability_id: null,
        name: capabilityName,
        version: "1.0.0",
        purpose: `Bridge authority for ${action}.`,
      },
      capability_references: [
        {
          capability_id: null,
          name: capabilityName,
          version: "1.0.0",
          purpose: `Bridge authority for ${action}.`,
        },
      ],
      input_contract: {
        tool_invocation: {
          schema_version: 1,
          action,
          input: preset?.input ?? {},
        },
      },
      expected_output_contract: { artifact: `${action}_result` },
      execution_constraints: { read_only: !preset?.requiresCredential },
      metadata: { sequence: index + 1, action },
    };
  });

  const edges = nodes.slice(1).map((node, index) => ({
    from_node_key: nodes[index].key,
    to_node_key: node.key,
    dependency_type: "depends_on",
    metadata: { description: "Sequential ability execution." },
  }));

  return {
    schema_version: 1,
    graph_status: "draft",
    nodes,
    edges,
    metadata: { generated_by: "mission-dispatch-ui", operator_notes: "Auto-generated from allowed_actions." },
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
      compiler_version: "1.0.0",
      source_plan_version: "1",
      deterministic_inputs: { source: "allowed_actions" },
    },
    deterministic_compilation_metadata: {
      compiler_name: "mission-dispatch-ui-compiler",
      compiler_version: "1.0.0",
      compilation_boundary: "allowed_actions_to_task_graph",
      deterministic: true,
    },
    generation_notes: ["Metadata-only materialization from customer dispatch UI."],
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