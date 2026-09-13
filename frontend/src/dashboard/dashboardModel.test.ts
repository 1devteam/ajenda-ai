import { describe, expect, it } from "vitest";
import type { CrmRecordItem, MissionListItem } from "../types";
import {
  bucketMissionStatus,
  buildOnboardingChecklist,
  countStatusBreakdown,
  filterRecordsByWorkflow,
  isActiveMission,
  resolveAttentionBanner,
  resolvePrimaryAction,
  usagePercent,
} from "./dashboardModel";

function mission(status: string, overrides: Partial<MissionListItem> = {}): MissionListItem {
  return {
    mission_id: "m1",
    objective: "Test",
    status,
    scope_limits: [],
    allowed_actions: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("dashboardModel", () => {
  it("filters CRM records by workflow context and defaults missing context to CRM", () => {
    const records = [
      { id: "crm", record_type: "contact", data: { name: "CRM" } },
      { id: "gtm", record_type: "account", data: { name: "GTM", workflow_context: "gtm" } },
      { id: "vertical", record_type: "opportunity", data: { name: "Vertical", workflow_context: "vertical" } },
    ] as CrmRecordItem[];
    expect(filterRecordsByWorkflow(records, "all").map((item) => item.id)).toEqual([
      "crm",
      "gtm",
      "vertical",
    ]);
    expect(filterRecordsByWorkflow(records, "crm").map((item) => item.id)).toEqual(["crm"]);
    expect(filterRecordsByWorkflow(records, "gtm").map((item) => item.id)).toEqual(["gtm"]);
    expect(filterRecordsByWorkflow(records, "vertical").map((item) => item.id)).toEqual(["vertical"]);
  });

  it("buckets mission statuses without double-counting", () => {
    const breakdown = countStatusBreakdown([
      mission("planned"),
      mission("running"),
      mission("completed"),
      mission("failed"),
      mission("approved"),
      mission("paused"),
    ]);
    expect(breakdown).toEqual({
      planned: 3,
      running: 1,
      completed: 1,
      failed: 1,
    });
  });

  it("maps MissionState values onto dashboard buckets", () => {
    expect(bucketMissionStatus("queued")).toBe("planned");
    expect(bucketMissionStatus("approved")).toBe("planned");
    expect(bucketMissionStatus("paused")).toBe("planned");
    expect(bucketMissionStatus("running")).toBe("running");
    expect(bucketMissionStatus("completed")).toBe("completed");
    expect(bucketMissionStatus("failed")).toBe("failed");
  });

  it("keeps approved work active but removes paused review holds", () => {
    expect(isActiveMission(mission("approved"))).toBe(true);
    expect(isActiveMission(mission("paused"))).toBe(false);
    expect(isActiveMission(mission("queued"))).toBe(true);
    expect(isActiveMission(mission("completed"))).toBe(false);
    expect(isActiveMission(mission("cancelled"))).toBe(false);
  });

  it("does not count cancelled or archived as failed", () => {
    expect(bucketMissionStatus("cancelled")).toBe("other");
    expect(bucketMissionStatus("canceled")).toBe("other");
    expect(bucketMissionStatus("archived")).toBe("other");
    const breakdown = countStatusBreakdown([
      mission("failed"),
      mission("cancelled"),
      mission("archived"),
    ]);
    expect(breakdown.failed).toBe(1);
    expect(breakdown).toEqual({
      planned: 0,
      running: 0,
      completed: 0,
      failed: 1,
    });
  });

  it("prioritizes approvals for primary action", () => {
    expect(
      resolvePrimaryAction({ pendingApprovals: 3, wizardDone: true, emailVerified: true }).id,
    ).toBe("approvals");
    expect(
      resolvePrimaryAction({ pendingApprovals: 0, wizardDone: false, emailVerified: true }).id,
    ).toBe("setup");
    expect(
      resolvePrimaryAction({ pendingApprovals: 0, wizardDone: true, emailVerified: true }).id,
    ).toBe("launch");
  });

  it("picks one banner by priority quota > setup > email", () => {
    expect(
      resolveAttentionBanner({
        quotaPct: 90,
        wizardDone: false,
        emailVerified: false,
      })?.id,
    ).toBe("quota");
    expect(
      resolveAttentionBanner({
        quotaPct: 10,
        wizardDone: false,
        emailVerified: false,
      })?.id,
    ).toBe("setup");
    expect(
      resolveAttentionBanner({
        quotaPct: null,
        wizardDone: true,
        emailVerified: false,
      })?.id,
    ).toBe("email");
  });

  it("builds checklist steps", () => {
    const steps = buildOnboardingChecklist({
      wizardDone: true,
      hasConnections: false,
      hasLaunchedMission: false,
    });
    expect(steps.map((s) => [s.id, s.done])).toEqual([
      ["setup", true],
      ["connect", false],
      ["launch", false],
    ]);
  });

  it("computes usage percent", () => {
    expect(usagePercent(80, 100)).toBe(80);
    expect(usagePercent(1, 0)).toBeNull();
    expect(usagePercent(1, -1)).toBeNull();
  });
});
