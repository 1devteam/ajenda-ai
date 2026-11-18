import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import MissionDispatchPage from "./MissionDispatchPage";

const auth = vi.hoisted(() => ({ session: { tenantId: "tenant-a" } }));
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => auth }));
vi.mock("../api/client", () => ({
  getMissionLifecycle: vi.fn(async () => ({
    mission: { mission_id: "mission-1", objective: "Read approved profile", status: "completed" },
    intake: {}, completeness: {}, missing_next_steps: [], optional_closeout_steps: [],
  })),
  getMissionRuntimeReadiness: vi.fn(async () => ({ ready: true, blockers: [], warnings: [] })),
  getMissionDispatchReadiness: vi.fn(async () => ({ queued_task_count: 0 })),
  getMissionRuntimeTaskMaterialization: vi.fn(async () => { throw { status: 404 }; }),
  getMissionRuntimeEvidence: vi.fn(async () => null),
  getMissionDeliverable: vi.fn(async () => { throw { status: 404 }; }),
  getProfileDeliverable: vi.fn(async () => ({
    schema_version: 1, kind: "business_profile_brief", mission_id: "mission-1", objective: "Read approved profile",
    profile_id: "profile-1", approved_facts: {}, profile_brief: { facts: { business_name: "Ajenda AI" } },
    missing_fields: ["description"], conflicting_fields: [], evidence_ids: ["unrelated-evidence"],
    profile_source_evidence_ids: ["evidence-1"], complete: true,
    grants_execution_authority: false,
  })),
}));

let root: Root;
let container: HTMLDivElement;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

it("shows the existing profile artifact and evidence after the generic deliverable is absent", async () => {
  await act(async () => {
    root.render(<MemoryRouter initialEntries={["/missions/mission-1"]}><Routes><Route path="/missions/:missionId" element={<MissionDispatchPage />} /></Routes></MemoryRouter>);
  });
  expect(container.textContent).toContain("Approved business profile");
  expect(container.textContent).toContain("Ajenda AI");
  expect(container.textContent).toContain("profile-1");
  expect(container.textContent).toContain("evidence-1");
  expect(container.textContent).not.toContain("unrelated-evidence");
  expect(container.textContent).toContain("Missing fields: description");
});
