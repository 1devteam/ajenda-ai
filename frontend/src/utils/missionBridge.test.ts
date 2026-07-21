import { describe, expect, it } from "vitest";
import { buildTaskGraphPayload, seedToolInputForAction } from "./missionBridge";

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

  it("wires sequential input_bindings for ability world-state", () => {
    const graph = buildTaskGraphPayload(
      ["web.research", "gtm.lead_enrich", "gtm.email_draft"],
      "Find three roofing companies in Fayetteville AR",
    );
    expect(graph.nodes).toHaveLength(3);
    const enrichMeta = (graph.nodes[1] as { metadata: { input_bindings: Array<Record<string, string>> } })
      .metadata;
    const draftMeta = (graph.nodes[2] as { metadata: { input_bindings: Array<Record<string, string>> } })
      .metadata;
    expect(enrichMeta.input_bindings).toEqual([
      {
        from_step: "ability-web-research",
        output_path: "$.prospect_candidates",
        to_step: "ability-gtm-lead_enrich",
        input_path: "$.input.prospects",
      },
    ]);
    expect(draftMeta.input_bindings).toEqual([
      {
        from_step: "ability-gtm-lead_enrich",
        output_path: "$.enriched_prospects",
        to_step: "ability-gtm-email_draft",
        input_path: "$.input.prospects",
      },
    ]);
  });

  it("does not seed demo Example Roofing or example.com recipients", () => {
    const graph = buildTaskGraphPayload(
      ["gtm.lead_enrich", "gtm.email_draft"],
      "Identify roofing prospects in Austin",
    );
    const enrichInput = (
      graph.nodes[0] as {
        input_contract: { tool_invocation: { input: Record<string, unknown> } };
      }
    ).input_contract.tool_invocation.input;
    const draftInput = (
      graph.nodes[1] as {
        input_contract: { tool_invocation: { input: Record<string, unknown> } };
      }
    ).input_contract.tool_invocation.input;
    expect(JSON.stringify(enrichInput)).not.toContain("Example Roofing");
    expect(JSON.stringify(enrichInput)).not.toContain("example-roofing.com");
    expect(draftInput.recipient).toBe("pending.binding@invalid.local");
    expect(JSON.stringify(draftInput)).not.toContain("prospect@example.com");
  });
});

describe("seedToolInputForAction", () => {
  it("uses mission objective for web.research public search", () => {
    const input = seedToolInputForAction(
      "web.research",
      "research roofing companies in fayetteville AR identify three",
    );
    expect(input.query).toContain("roofing");
    expect(input.include_public_search).toBe(true);
  });
});
