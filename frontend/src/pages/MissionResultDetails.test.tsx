import { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router";
import { expect, it, vi } from "vitest";
import type { MissionDeliverableResponse } from "../types";
import MissionDispatchPage from "./MissionDispatchPage";

const { getDeliverable, session } = vi.hoisted(() => ({
  getDeliverable: vi.fn(),
  session: { tenantId: "tenant-a" },
}));
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => ({ session }) }));
vi.mock("../api/client", () => ({
  getMissionLifecycle: vi.fn(async () => ({
    mission: { mission_id: "mission-1", objective: "Review the recorded result", status: "completed" },
    intake: {}, completeness: {}, missing_next_steps: [], optional_closeout_steps: [],
  })),
  getMissionRuntimeReadiness: vi.fn(async () => ({ ready: true, blockers: [], warnings: [] })),
  getMissionDispatchReadiness: vi.fn(async () => ({ queued_task_count: 0 })),
  getMissionRuntimeTaskMaterialization: vi.fn(async () => { throw { status: 404 }; }),
  getMissionRuntimeEvidence: vi.fn(async () => null),
  getMissionDeliverable: getDeliverable,
}));

async function readReopenedResult(result: Partial<MissionDeliverableResponse>): Promise<string> {
  getDeliverable.mockResolvedValue({
    prospects: [],
    task_state: { all_succeeded: true },
    completion: { artifact_complete: true, assembly_errors: [] },
    ...result,
  });
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  try {
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={["/missions/mission-1"]}>
          <Routes><Route path="/missions/:missionId" element={<MissionDispatchPage />} /></Routes>
        </MemoryRouter>,
      );
    });
    return container.querySelector('[aria-label="Mission deliverable"]')?.textContent ?? "";
  } finally {
    await act(async () => root.unmount());
    container.remove();
  }
}

it("renders the persisted goal assessment, its evidence, and its narrower scope", async () => {
  const text = await readReopenedResult({
    artifacts: { goal_progress_evaluation: {
      status: "insufficient_data",
      evaluation_scope: "mission_instruction_only",
      confidence: 0.25,
      kpi_evaluations: [{ kpi_id: "kpi", metric: "Retention", current_value: 0, target_value: 1 }],
      evidence_gaps: [{ message: "Historical measurements were unavailable." }],
      supporting_evidence_ids: ["evidence-1"],
    } },
  });
  expect(text).toContain("Goal evaluation");
  expect(text).toContain("insufficient data");
  expect(text).toContain("A stored goal was unavailable.");
  expect(text).toContain("Current 0");
  expect(text).toContain("Historical measurements were unavailable.");
  expect(text).toContain("evidence-1");
  expect(text).not.toContain("No prospect candidates were produced.");
});

it("explains research shortfall using separately recorded discovery and verification", async () => {
  const text = await readReopenedResult({
    result_semantics: { public_research_stages: [
      { stage: "discovery", status: "completed", candidates: [{ company: "Directory candidate" }] },
      {
        stage: "verification", status: "completed", observed_count: 0, requested_quantity: 3,
        verified_candidates: [],
        unverified_observations: [{ company: "Directory candidate", reason: "identity_unverified" }],
      },
    ] },
    completion: { artifact_complete: false, complete: false, missing_fields: [], invalid_fields: [], assembly_errors: [] },
  });
  expect(text).toContain("Public research");
  expect(text).toContain("Candidates found");
  expect(text).toContain("Directory candidate");
  expect(text).toContain("Verifier recorded 0 of 3 requested identities.");
  expect(text).toContain("Rejected or unresolved observations");
  expect(text).toContain("identity unverified");
  expect(text).toContain("No research report was recorded.");
});

it("distinguishes a failed verification stage from a completed empty result", async () => {
  const text = await readReopenedResult({
    result_semantics: { public_research_stages: [{ stage: "verification", status: "failed" }] },
  });
  expect(text).toContain("Public identity verification · failed");
  expect(text).not.toContain("No candidates were verified.");
  expect(text).not.toContain("evidence-backed empty result");
});

it("shows the verification minimum separately from the requested cap", async () => {
  const text = await readReopenedResult({
    result_semantics: { public_research_stages: [{
      stage: "verification",
      status: "completed",
      observed_count: 1,
      requested_quantity: 3,
      minimum_verified_quantity: 1,
    }] },
  });
  expect(text).toContain("Verified 1 identity. Minimum 1, limit 3.");
});

it("renders the report rows and their source evidence in the normal mission view", async () => {
  const text = await readReopenedResult({
    artifacts: { research_report: {
      result_semantics: "observed_candidates",
      comparison: [{
        company: "Example Company",
        website: "https://example.com",
        summary: "Observed from the company website.",
        identity_status: "verified",
        sources: ["https://example.com/about"],
      }],
    } },
  });
  expect(text).toContain("Research report");
  expect(text).toContain("Example Company");
  expect(text).toContain("Identity verified");
  expect(text).toContain("Observed from the company website.");
  expect(text).toContain("https://example.com/about");
});

it("labels sources in mixed discovery readback and exposes missing public provider evidence", async () => {
  const text = await readReopenedResult({
    result_semantics: { public_research_stages: [{
      stage: "discovery",
      status: "completed",
      public_search_observed: false,
      candidates: [
        { company: "Internal Company", source_scope: "tenant_internal", identity_status: "verified", identity_evidence_urls: ["https://example.com"] },
        { company: "Fixture Company", source_scope: "local_fixture" },
      ],
    }] },
  });
  expect(text).toContain("Internal CompanyInternal record");
  expect(text).toContain("Fixture CompanyFixture evidence");
  expect(text).toContain("Candidate source URLs");
  expect(text).not.toContain("Internal recordverified");
  expect(text).toContain("No public search provider response was recorded.");
});
