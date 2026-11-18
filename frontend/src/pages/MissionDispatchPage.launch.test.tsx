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
  getMissionDispatchReadiness: vi.fn(),
  getMissionRuntimeTaskMaterialization: vi.fn(),
  getMissionRuntimeEvidence: vi.fn(),
}));
const auth = vi.hoisted(() => ({ session: { tenantId: "tenant-a" } }));

vi.mock("../auth/AuthProvider", () => ({ useAuth: () => auth }));
vi.mock("../api/client", () => ({
  ...api,
  getMissionRuntimeReadiness: vi.fn(async () => ({ ready: false, blockers: [], warnings: [] })),
}));

let root: Root;
let container: HTMLDivElement;

function mockLifecycle(
  composition: { ready_to_start: boolean; proposal_status?: string },
  status = "planned",
  completeness: Record<string, boolean> = { has_plan: true, has_task_graph: true },
) {
  api.getMissionLifecycle.mockResolvedValue({
    mission: { mission_id: "mission-1", objective: "Read internal CRM accounts", status },
    intake: { allowed_actions: ["record.search"], context: { composition } },
    completeness,
    missing_next_steps: [],
    optional_closeout_steps: [],
  });
}

async function mountMission(suffix: string) {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={[`/missions/mission-1${suffix}`]}>
        <Routes>
          <Route path="/missions/:missionId" element={<MissionDispatchPage />} />
        </Routes>
      </MemoryRouter>,
    );
  });
}

async function renderMission(suffix = "") {
  await mountMission(suffix);
  const button = [...container.querySelectorAll("button")].find(
    (candidate) => candidate.textContent === "Start execution",
  );
  if (!button) throw new Error("Start execution button is missing");
  return button;
}

beforeEach(() => {
  vi.resetAllMocks();
  api.getMissionDispatchReadiness.mockResolvedValue({ queued_task_count: 0, queue_admission_reference: null });
  api.getMissionRuntimeTaskMaterialization.mockRejectedValue({ status: 404 });
  api.getMissionRuntimeEvidence.mockResolvedValue(null);
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


function stageStatus(stage: string) {
  return [...container.querySelectorAll(".dispatch-step")]
    .find((row) => row.querySelector("strong")?.textContent === stage)
    ?.querySelector(".dispatch-step-status")?.textContent;
}

const completedGraph = {
  has_plan: true, has_task_graph: true, has_materialization: true, has_runtime_admission: true,
};

it.each([
  { status: "admitted", currentIds: ["a", "b"], coveredIds: ["b", "a"], admittedIds: ["a", "b"], expected: "complete" },
  { status: "partially_admitted", currentIds: ["a", "b"], coveredIds: ["a", "b"], admittedIds: ["a"], expected: "partially admitted" },
  { status: "admitted", currentIds: ["a"], coveredIds: ["old"], admittedIds: ["old"], expected: "blocked" },
  { status: "admitted", currentIds: ["a", "b"], coveredIds: ["a", "b"], admittedIds: ["a"], expected: "blocked" },
  { status: "admitted", currentIds: ["a"], coveredIds: ["a"], admittedIds: ["a"], tenantId: "other-tenant", expected: "blocked" },
])("reads recorded queue admission after the queue drains ($expected)", async ({
  status, currentIds, coveredIds, admittedIds, tenantId, expected,
}) => {
  mockLifecycle({ ready_to_start: true }, "completed", completedGraph);
  api.getMissionRuntimeTaskMaterialization.mockResolvedValue({
    mission_id: "mission-1", tenant_id: "tenant-a", materialization_status: "materialized",
    created_execution_task_ids: currentIds,
  });
  api.getMissionDispatchReadiness.mockResolvedValue({
    queued_task_count: 0,
    queue_admission_reference: {
      mission_id: "mission-1", tenant_id: tenantId ?? "tenant-a", admission_status: status,
      materialized_execution_task_ids: coveredIds, admitted_execution_task_ids: admittedIds,
    },
  });

  await mountMission("");

  expect(stageStatus("Task materialization")).toBe("complete");
  expect(stageStatus("Queue admission")).toBe(expected);
  expect(container.textContent).not.toContain("Next incomplete stage");
  expect(container.textContent).not.toContain("Queue for workers");
});

it.each(["completed", "failed", "cancelled", "archived"])("opens a %s mission for review without launching", async (status) => {
  mockLifecycle({ ready_to_start: true }, status, completedGraph);
  api.getMissionDispatchReadiness.mockResolvedValue({ queued_task_count: 2, queue_admission_reference: null });

  await mountMission("?execute=1");

  expect(api.launchMission).not.toHaveBeenCalled();
  expect(container.textContent).not.toContain("Start execution");
  expect(container.textContent).not.toContain("Provision authority");
  expect(stageStatus("Queue admission")).toBe("not recorded");
  expect([...container.querySelectorAll("a")].find((link) => link.textContent === "Plan a new run")?.getAttribute("href"))
    .toBe("/missions");
});

it("shows the direct task path when task evidence exists without graph stages", async () => {
  mockLifecycle({ ready_to_start: true }, "completed", {
    has_plan: false, has_task_graph: false, has_materialization: false, has_runtime_admission: false,
  });
  api.getMissionRuntimeEvidence.mockResolvedValue({
    task_flows: [{ task_id: "direct-task", node_key: null, status: "completed", queue_admitted: true }],
    execution_events: [], record_flows: [], contradictions: [], missing_evidence: [],
  });

  await mountMission("");

  expect(container.textContent).toContain("Direct task execution");
  expect(container.textContent).toContain("Observed execution flow");
  expect(container.textContent).not.toContain("Recorded pipeline stages");
});


it("shows the recorded reason a research mission missed acceptance even without a deliverable", async () => {
  mockLifecycle({ ready_to_start: true }, "failed", completedGraph);
  api.getMissionRuntimeEvidence.mockResolvedValue({
    acceptance: {
      status: "partially_met",
      reasons: ["required 3 verified prospect identities, produced 0"],
    },
    first_divergence: "mission:acceptance",
    task_flows: [], execution_events: [], record_flows: [], contradictions: [], missing_evidence: [],
  });

  await mountMission("");

  const acceptance = container.querySelector('[aria-label="Outcome acceptance"]');
  expect(acceptance?.textContent).toContain("Requirements partially met");
  expect(acceptance?.textContent).toContain("required 3 verified prospect identities, produced 0");
  expect(container.textContent).toContain("mission:acceptance");
});

it("switches from launch to review as the monitored mission completes", async () => {
  mockLifecycle({ ready_to_start: true });
  api.launchMission.mockImplementation(async () => {
    mockLifecycle({ ready_to_start: true }, "completed", completedGraph);
    return { queued_task_ids: ["finished-task"], pending_review_task_ids: [], blockers: [] };
  });
  api.getTaskStatus.mockResolvedValue({ status: "completed" });

  const button = await renderMission();
  await act(async () => button.click());

  expect(api.getTaskStatus).toHaveBeenCalledWith(auth.session, "finished-task");
  expect(container.querySelector(".mission-context-banner .status-pill")?.textContent).toBe("completed");
  expect(container.textContent).toContain("Plan a new run");
  expect(container.textContent).not.toContain("Start execution");
});
