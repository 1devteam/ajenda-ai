import { describe, expect, it } from "vitest";
import { seedToolInputForAction } from "./missionBridge";

describe("seedToolInputForAction", () => {
  it("uses mission objective for web.research public search", () => {
    const input = seedToolInputForAction(
      "web.research",
      "research roofing companies in fayetteville AR identify three",
    );
    expect(input.query).toContain("roofing");
    expect(input.include_public_search).toBe(true);
  });

  it("does not seed demo Example Roofing or example.com recipients", () => {
    const enrichInput = seedToolInputForAction("gtm.lead_enrich", "Identify roofing prospects in Austin");
    const draftInput = seedToolInputForAction("gtm.email_draft", "Identify roofing prospects in Austin");
    expect(JSON.stringify(enrichInput)).not.toContain("Example Roofing");
    expect(JSON.stringify(enrichInput)).not.toContain("example-roofing.com");
    expect(draftInput.recipient).toBe("pending.binding@invalid.local");
    expect(JSON.stringify(draftInput)).not.toContain("prospect@example.com");
  });
});
