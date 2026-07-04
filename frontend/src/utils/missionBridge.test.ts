import { describe, expect, it } from "vitest";
import { buildTaskGraphPayload } from "./missionBridge";

describe("buildTaskGraphPayload", () => {
  it("emits canonical v1 task graph node fields", () => {
    const graph = buildTaskGraphPayload(["gtm.email_draft", "gtm.crm_upsert"]);
    expect(graph.schema_version).toBe(1);
    expect(graph.graph_status).toBe("draft");
    expect(graph.nodes).toHaveLength(2);

    const node = graph.nodes[0] as Record<string, unknown>;
    expect(node).toHaveProperty("node_key");
    expect(node).toHaveProperty("output_contract");
    expect(node).not.toHaveProperty("expected_output_contract");
    expect(node).not.toHaveProperty("intended_task_type");
    expect(node).not.toHaveProperty("name");
    expect(node).not.toHaveProperty("execution_constraints");
  });
});