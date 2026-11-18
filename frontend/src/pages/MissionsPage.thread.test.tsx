import { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router";
import { expect, it, vi } from "vitest";
import MissionsPage from "./MissionsPage";

const api = vi.hoisted(() => ({
  session: { tenantId: "tenant-a" },
  compose: vi.fn(),
}));
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => ({ session: api.session }) }));
vi.mock("../api/client", () => ({
  composeMission: api.compose,
  confirmMissionComposition: vi.fn(),
  listMissions: vi.fn(async () => ({ missions: [] })),
}));

it("keeps the interpretation thread for revisions and clears it for a new request", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  api.compose.mockResolvedValue({
    proposal_id: "proposal-1",
    interpretation_thread_id: "thread-1",
    mission_brief: { objective: "Read our profile", success_criteria: [], constraints: [] },
    planned_steps: [],
    missing_connections: [],
    clarifications: [],
    forbidden_actions: [],
    ready_to_start: false,
  });
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);

  async function enter(instruction: string) {
    const textarea = container.querySelector("textarea")!;
    const valueSetter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
    await act(async () => {
      valueSetter.call(textarea, instruction);
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => {
      container.querySelector<HTMLButtonElement>('button[type="submit"]')!.click();
    });
  }

  try {
    await act(async () => root.render(<MemoryRouter><MissionsPage /></MemoryRouter>));
    await enter("Read our profile.");
    expect(api.compose).toHaveBeenNthCalledWith(1, api.session, {
      instruction: "Read our profile.",
      interpretation_thread_id: undefined,
    });
    await enter("Read the approved profile.");
    expect(api.compose).toHaveBeenNthCalledWith(2, api.session, {
      instruction: "Read the approved profile.",
      interpretation_thread_id: "thread-1",
    });

    await act(async () => {
      const newRequest = [...container.querySelectorAll("button")].find((button) => button.textContent === "New request");
      newRequest!.click();
    });
    expect(container.querySelector("textarea")!.value).toBe("");
    await enter("Check upcoming Calendar events.");
    expect(api.compose).toHaveBeenNthCalledWith(3, api.session, {
      instruction: "Check upcoming Calendar events.",
      interpretation_thread_id: undefined,
    });
  } finally {
    await act(async () => root.unmount());
    container.remove();
  }
});
