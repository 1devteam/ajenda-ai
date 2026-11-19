import { expect, it, vi } from "vitest";
import { upsertBusinessProfileFact } from "../api/client";
import { BUSINESS_PROFILE_FIELDS } from "../config/businessProfileFields";
import type { CustomerSession } from "../types";
import { readProfileList, readProfileText } from "./businessProfile";
import { saveBusinessProfileFacts } from "./saveBusinessProfileFacts";

vi.mock("../api/client", () => ({
  upsertBusinessProfileFact: vi.fn(),
}));

it("loads profile aliases and saves the approved fields consumed by company briefs", async () => {
  const description = BUSINESS_PROFILE_FIELDS.find((field) => field.category === "description");
  const differentiators = BUSINESS_PROFILE_FIELDS.find((field) => field.category === "differentiators");
  expect(description).toBeDefined();
  expect(differentiators).toBeDefined();
  const facts = { about: { value: "Governed operations." }, advantages: { items: ["Recorded execution"] } };
  const overview = readProfileText(facts, "description", description?.fallbackKeys);
  const distinct = readProfileList(facts, "differentiators", differentiators?.fallbackKeys);
  const session = { tenantId: "tenant-a" } as CustomerSession;
  await saveBusinessProfileFacts(session, { description: overview, differentiators: distinct.join("\n") }, "test");
  expect(upsertBusinessProfileFact).toHaveBeenCalledWith(session, "description", {
    approved_fact: { value: "Governed operations." },
    provenance_metadata: { source: "test" },
  });
  expect(upsertBusinessProfileFact).toHaveBeenCalledWith(session, "differentiators", {
    approved_fact: { items: ["Recorded execution"] },
    provenance_metadata: { source: "test" },
  });
});
