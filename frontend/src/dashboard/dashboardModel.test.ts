import { describe, expect, it } from "vitest";
import type { MissionListItem } from "../types";
import {
  bucketMissionStatus,
  buildOnboardingChecklist,
  countStatusBreakdown,
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
  it("buckets mission statuses without double-counting", () => {
    const breakdown = countStatusBreakdown([
      mission("planned"),
      mission("running"),
      mission("completed"),
      mission("failed"),
      mission("in_progress"),
    ]);
    expect(breakdown).toEqual({
      planned: 1,
      running: 2,
      completed: 1,
      failed: 1,
    });
  });

  it("maps known aliases", () => {
    expect(bucketMissionStatus("queued")).toBe("planned");
    expect(bucketMissionStatus("executing")).toBe("running");
    expect(bucketMissionStatus("succeeded")).toBe("completed");
    expect(bucketMissionStatus("dead_letter")).toBe("failed");
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
