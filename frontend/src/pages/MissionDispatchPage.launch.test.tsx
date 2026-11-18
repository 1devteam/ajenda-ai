import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import MissionDispatchPage from "./MissionDispatchPage";

const api = vi.hoisted(() => ({
  getMissionLifecycle: vi.fn(),
  launchMission: vi.fn(),
  getTaskStatus: vi.fn(),
  getMissionDeliverable: vi.fn(async () => null as unknown),
}));
const auth = vi.hoisted(() => ({ session: { tenantId: "tenant-a" } }));

vi.mock("../auth/AuthProvider", () => ({ useAuth: () => auth }));
vi.mock("../api/client", () => ({
  ...api,
  getMissionRuntimeReadiness: vi.fn(async () => ({ ready: false, blockers: [], warnings: [] })),
  getMissionDispatchReadiness: vi.fn(async () => ({ queued_task_count: 0 })),
  getMissionRuntimeEvidence: vi.fn(async () => null),
}));

let root: Root;
let container: HTMLDivElement;

function mockLifecycle(composition: { ready_to_start: boolean; proposal_status?: string }) {
  api.getMissionLifecycle.mockResolvedValue({
    mission: { mission_id: "mission-1", objective: "Read internal CRM accounts", status: "planned" },
    intake: { allowed_actions: ["record.search"], context: { composition } },
    completeness: { has_plan: true, has_task_graph: true },
    missing_next_steps: [],
    optional_closeout_steps: [],
  });
}

async function renderMission(suffix = "") {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={[`/missions/mission-1${suffix}`]}>
        <Routes>
          <Route path="/missions/:missionId" element={<MissionDispatchPage />} />
        </Routes>
      </MemoryRouter>,
    );
  });
  const button = [...container.querySelectorAll("button")].find(
    (candidate) => candidate.textContent === "Start execution",
  );
  if (!button) throw new Error("Start execution button is missing");
  return button;
}

beforeEach(() => {
  vi.resetAllMocks();
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

it.each(["", "?execute=1"])("explains an unresolved composition before launch (%s)", async (suffix) => {
  mockLifecycle({ ready_to_start: false, proposal_status: "gaps_open" });
  const button = await renderMission(suffix);

  expect(button.disabled).toBe(true);
  expect(container.querySelector("#" + button.getAttribute("aria-describedby"))?.textContent)
    .toContain("Ajenda needs clarification");
  expect(api.launchMission).not.toHaveBeenCalled();
});

it("shows graph compilation errors beside Start execution", async () => {
  mockLifecycle({ ready_to_start: true });
  api.launchMission.mockRejectedValue({
    status: 422,
    body: {
      detail: {
        code: "COMPILE_NOT_READY",
        compile: { blockers: [{ message: "An account source binding is missing." }] },
      },
    },
  });

  const button = await renderMission();
  expect(button.disabled).toBe(false);
  await act(async () => button.click());

  expect(api.launchMission).toHaveBeenCalledWith(auth.session, "mission-1");
  const alert = container.querySelector("[role=alert]");
  expect(alert?.textContent).toContain("Mission launch stopped at graph compilation");
  expect(alert?.textContent).toContain("An account source binding is missing.");
});

it("shows queue blockers and monitors tasks that were queued", async () => {
  mockLifecycle({ ready_to_start: true });
  api.launchMission.mockResolvedValue({
    queued_task_ids: ["queued-task"],
    pending_review_task_ids: ["review-task"],
    blockers: [{
      code: "policy_review_required",
      message: "Task sent to policy review.",
      task_id: "review-task",
    }],
  });
  api.getTaskStatus.mockResolvedValue({ status: "queued" });

  const button = await renderMission();
  await act(async () => button.click());

  const alert = container.querySelector("[role=alert]");
  expect(alert?.textContent).toContain("1 task(s) queued in this launch.");
  expect(alert?.textContent).toContain("1 task(s) waiting for policy review.");
  expect(alert?.textContent).toContain("policy_review_required");
  expect(alert?.textContent).toContain("Task sent to policy review.");
  expect(api.getTaskStatus).toHaveBeenCalledWith(auth.session, "queued-task");
});


it("shows the next incomplete stage and keeps manual controls in diagnostics", async () => {
  mockLifecycle({ ready_to_start: true });
  await renderMission();

  expect(container.textContent).toContain("Next incomplete stage: Graph materialization");
  expect(container.querySelector("details.dispatch-diagnostics")?.hasAttribute("open")).toBe(false);
  expect(container.querySelector("details.dispatch-diagnostics")?.textContent).toContain("Provision authority");
});

it.each([
  { rows: [{ id: "a", name: "Ajenda Test Customer - Cedar Supply" }], complete: true, expected: "Ajenda Test Customer - Cedar Supply" },
  { rows: [], complete: true, expected: "No matching internal CRM records." },
  { rows: [], complete: false, expected: "No verified internal CRM search result is available yet." },
])("distinguishes CRM result evidence ($expected)", async ({ rows, complete, expected }) => {
  mockLifecycle({ ready_to_start: true });
  api.getMissionDeliverable.mockResolvedValue({
    artifacts: { crm_records: rows },
    prospects: [],
    task_state: { all_succeeded: complete },
    completion: { complete, artifact_complete: complete, assembly_errors: [] },
  });

  await renderMission();
  expect(container.querySelector('[aria-label="Mission deliverable"]')?.textContent).toContain("Internal CRM search");
  expect(container.querySelector('[aria-label="Internal CRM search results"]')?.textContent).toContain(expected);
  expect(container.textContent).not.toContain("No prospect candidates were produced");
});
