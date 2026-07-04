import { describe, expect, it } from "vitest";
import {
  CAPSTONE_OUTREACH_ACTIONS,
  CAPSTONE_OUTREACH_PRESETS,
  MISSION_ABILITY_PRESETS,
  MISSION_ALLOWED_ACTION_OPTIONS,
} from "./missionAbilities";

describe("missionAbilities", () => {
  it("includes document actions in allowed options", () => {
    const actions = MISSION_ALLOWED_ACTION_OPTIONS.map((item) => item.action);
    expect(actions).toContain("document.generate");
    expect(actions).toContain("document.search");
    expect(actions).toContain("document.read");
  });

  it("uses recipient/topic/tone for gtm.email_draft preset", () => {
    const draft = MISSION_ABILITY_PRESETS.find((item) => item.action === "gtm.email_draft");
    expect(draft).toBeDefined();
    expect(draft?.input).toMatchObject({
      recipient: expect.any(String),
      topic: expect.any(String),
      tone: expect.any(String),
    });
    expect(draft?.input).not.toHaveProperty("body");
    expect(draft?.input).not.toHaveProperty("subject");
  });

  it("exposes capstone outreach bundle presets in mission order", () => {
    expect([...CAPSTONE_OUTREACH_ACTIONS]).toEqual([
      "sales.research",
      "gtm.email_draft",
      "gtm.email_send",
      "gtm.crm_upsert",
    ]);
    expect(CAPSTONE_OUTREACH_PRESETS.map((item) => item.action)).toEqual([...CAPSTONE_OUTREACH_ACTIONS]);
  });
});