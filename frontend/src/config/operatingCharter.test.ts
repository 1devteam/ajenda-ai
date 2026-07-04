import { describe, expect, it } from "vitest";
import {
  DEFAULT_OPERATING_CHARTER,
  PREPARE_ACTION_OPTIONS,
  PERFORM_ACTION_OPTIONS,
  applyMayPerformToggle,
  applyNeverDoToggle,
} from "./operatingCharter";

describe("operating charter defaults", () => {
  it("exposes every default prepare action in the wizard options", () => {
    const optionActions = new Set<string>(PREPARE_ACTION_OPTIONS.map((item) => item.action));
    for (const action of DEFAULT_OPERATING_CHARTER.may_prepare) {
      expect(optionActions.has(action)).toBe(true);
    }
  });

  it("exposes every default perform action in the wizard options", () => {
    const optionActions = new Set<string>(PERFORM_ACTION_OPTIONS.map((item) => item.action));
    for (const action of DEFAULT_OPERATING_CHARTER.may_perform) {
      expect(optionActions.has(action)).toBe(true);
    }
  });
});

describe("operating charter mutual exclusion", () => {
  it("removes gtm.email_send from never_do when enabled in may_perform", () => {
    const next = applyMayPerformToggle(DEFAULT_OPERATING_CHARTER, "gtm.email_send", true);
    expect(next.may_perform).toContain("gtm.email_send");
    expect(next.never_do).not.toContain("gtm.email_send");
  });

  it("removes gtm.email_send from may_perform when enabled in never_do", () => {
    const seeded = applyMayPerformToggle(DEFAULT_OPERATING_CHARTER, "gtm.email_send", true);
    const next = applyNeverDoToggle(seeded, "gtm.email_send", true);
    expect(next.never_do).toContain("gtm.email_send");
    expect(next.may_perform).not.toContain("gtm.email_send");
  });
});