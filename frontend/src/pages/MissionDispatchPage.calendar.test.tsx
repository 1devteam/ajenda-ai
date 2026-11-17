import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import MissionDispatchPage from "./MissionDispatchPage";

const auth = vi.hoisted(() => ({ session: { tenantId: "tenant-a" } }));
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => auth }));
vi.mock("../api/client", () => ({
  getMissionLifecycle: vi.fn(async () => ({
    mission: { mission_id: "mission-1", objective: "Read upcoming Calendar events", status: "completed" },
    intake: {}, completeness: {}, missing_next_steps: [], optional_closeout_steps: [],
  })),
  getMissionRuntimeReadiness: vi.fn(async () => ({ ready: true, blockers: [], warnings: [] })),
  getMissionDispatchReadiness: vi.fn(async () => ({ queued_task_count: 0 })),
  getMissionRuntimeEvidence: vi.fn(async () => null),
  getMissionDeliverable: vi.fn(async () => ({
    mission_id: "mission-1", artifacts: { calendar_events: [{ id: "event-1", summary: "Example meeting" }] },
    prospects: [], task_state: { all_succeeded: true },
    completion: { artifact_complete: false, assembly_errors: [] },
    limitations: ["The upcoming time bound was not recorded."],
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

it("shows recorded calendar events with their evidence limitation", async () => {
  await act(async () => {
    root.render(<MemoryRouter initialEntries={["/missions/mission-1"]}><Routes><Route path="/missions/:missionId" element={<MissionDispatchPage />} /></Routes></MemoryRouter>);
  });
  expect(container.textContent).toContain("Calendar events returned");
  expect(container.textContent).toContain("event-1");
  expect(container.textContent).toContain("The upcoming time bound was not recorded.");
  expect(container.textContent).not.toContain("No prospect candidates were produced");
});
