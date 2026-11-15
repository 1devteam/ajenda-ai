import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import CredentialsPage from "./CredentialsPage";
import type { CustomerSession } from "../types";

const auth = vi.hoisted(() => ({ session: null as CustomerSession | null }));

vi.mock("../auth/AuthProvider", () => ({ useAuth: () => auth }));
vi.mock("../components/connections/ConnectorGrid", () => ({ default: () => null }));

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  auth.session = { tenantId: "tenant-a", authMode: "api_key", apiKey: "test-key", phase: "operational" };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ credentials: [] }), { status: 200 })),
  );
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

it("describes eligible HubSpot CRM credentials without directing users to CLI PAKs", async () => {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={["/credentials"]}>
        <CredentialsPage />
      </MemoryRouter>,
    );
  });

  const hubspotTab = [...container.querySelectorAll("button")].find(
    (button) => button.textContent === "HubSpot CRM",
  );
  expect(hubspotTab).toBeTruthy();
  await act(async () => hubspotTab!.dispatchEvent(new MouseEvent("click", { bubbles: true })));

  expect(container.textContent).toContain("HubSpot CRM access token");
  expect(container.textContent).toContain("HubSpot Service Key or private-app/static app token");
  expect(container.textContent).toContain("Do not paste a HubSpot CLI Personal Access Key.");
  expect(container.textContent).not.toContain("Paste HubSpot PAK");
});
