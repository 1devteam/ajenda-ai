import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MissionComposeResponse } from "../types";

const api = vi.hoisted(() => ({
  composeMission: vi.fn(),
  confirmMissionComposition: vi.fn(),
  listMissions: vi.fn(),
}));
const auth = vi.hoisted(() => ({
  session: { authMode: "api_key", tenantId: "tenant-1", phase: "operational" },
}));

vi.mock("../api/client", () => api);
vi.mock("../auth/AuthProvider", () => ({
  useAuth: () => auth,
}));
vi.mock("../utils/errors", async (importOriginal) => {
  const original = await importOriginal<typeof import("../utils/errors")>();
  return { ...original, newIdempotencyKey: () => "11111111-1111-4111-8111-111111111111" };
});

import MissionsPage from "./MissionsPage";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const RAW = "fnd 3 roofrs austin n draft intros dont send";
const INTERPRETATION =
  "Find 3 roofing companies in Austin and draft introductions. Do not send the introductions.";

const proposal: MissionComposeResponse = {
  proposal_id: "proposal-1",
  interpretation_thread_id: "thread-1",
  proposal_status: "proposal_ready",
  interpreted_instruction: INTERPRETATION,
  interpretation_fingerprint: "sha256:reviewed",
  mission_brief: {
    interpreted_instruction: INTERPRETATION,
    requested_outcomes: ["research_prospects", "prepare_outreach"],
    unsupported_outcomes: [],
    requested_quantity: 3,
    send_policy: { mode: "forbid", condition: "none" },
    contact_policy: { mode: "unknown", condition: "none" },
    publish_policy: { mode: "unknown", condition: "none" },
    write_policy: { mode: "unknown", condition: "none" },
    success_criteria: [{ description: "Produce 3 reviewed introductions" }],
    constraints: ["Do not send the introductions"],
    forbidden_outcomes: [],
    approval_preference: "review_before_external_action",
    target_entities: [],
    timing_constraints: [],
    context_requirements: [],
    clarifications: [],
    contradictions: [],
  },
  assigned_verticals: ["sales"],
  jobs: [],
  selected_abilities: [],
  forbidden_actions: ["gtm.email_send"],
  allowed_actions: ["web.research", "gtm.email_draft"],
  allowed_actions_provenance: { selected_by: "mission_composition_engine" },
  missing_connections: [],
  approval_gates: ["review_before_external_action"],
  planned_steps: [
    {
      step_key: "research",
      sequence: 1,
      title: "Research prospects",
      action_name: "web.research",
      depends_on: [],
    },
  ],
  task_graph_preview: { nodes: [] },
  clarifications: [],
  ready_to_start: true,
  grants_execution_authority: false,
  authority_class: "read_model",
};

let container: HTMLDivElement;
let root: Root;

async function renderPage() {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <MemoryRouter>
        <MissionsPage />
      </MemoryRouter>,
    );
  });
}

async function composeFromTextarea() {
  const textarea = container.querySelector("textarea") as HTMLTextAreaElement;
  await act(async () => {
    const valueSetter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
    valueSetter?.call(textarea, RAW);
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  });
  const form = container.querySelector("form") as HTMLFormElement;
  await act(async () => {
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}

beforeEach(() => {
  api.listMissions.mockResolvedValue({ missions: [], total: 0 });
  api.composeMission.mockResolvedValue(proposal);
  api.confirmMissionComposition.mockResolvedValue({
    mission_id: "mission-1",
    proposal_id: proposal.proposal_id,
    plan_id: "plan-1",
    allowed_actions: proposal.allowed_actions,
    forbidden_actions: proposal.forbidden_actions,
    task_graph: {},
    ready_to_start: true,
    runtime_queued: false,
    grants_execution_authority: false,
    next_steps: [],
  });
});

afterEach(async () => {
  if (root) {
    await act(async () => root.unmount());
  }
  container?.remove();
});

describe("MissionsPage interpretation review", () => {
  it("shows only the model interpretation in the review card and requires acknowledgement", async () => {
    await renderPage();
    await composeFromTextarea();

    const review = container.querySelector(".cc-mission-brief") as HTMLElement;
    expect(review.textContent).toContain(INTERPRETATION);
    expect(review.textContent).not.toContain(RAW);
    expect(review.textContent).toContain("Outcome: research prospects");
    expect(review.textContent).toContain("Quantity: 3");
    expect(review.textContent).toContain("Send condition: forbid");

    const confirm = Array.from(review.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("Confirm interpretation"),
    ) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);

    const checkbox = review.querySelector('input[type="checkbox"]') as HTMLInputElement;
    await act(async () => {
      checkbox.click();
    });
    expect(confirm.disabled).toBe(false);

    await act(async () => {
      confirm.click();
    });
    expect(api.confirmMissionComposition).toHaveBeenCalledWith(
      expect.anything(),
      proposal.proposal_id,
      {
        interpretation_fingerprint: proposal.interpretation_fingerprint,
        interpretation_confirmed: true,
        idempotency_key: "11111111-1111-4111-8111-111111111111",
      },
    );
  });

  it("cancels the proposal without creating a mission", async () => {
    await renderPage();
    await composeFromTextarea();
    const cancel = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("Cancel and revise"),
    ) as HTMLButtonElement;

    await act(async () => cancel.click());

    expect(container.querySelector(".cc-mission-brief")).toBeNull();
    expect(api.confirmMissionComposition).not.toHaveBeenCalled();
  });
});
