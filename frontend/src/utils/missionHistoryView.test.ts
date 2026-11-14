import { afterEach, describe, expect, it } from "vitest";
import type { MissionListItem } from "../types";
import {
  clearMissionHistoryCutoff,
  filterMissionHistoryForView,
  missionHistoryCutoffStorageKey,
  readMissionHistoryCutoff,
  setMissionHistoryCutoff,
} from "./missionHistoryView";

const tenantA = "tenant-a";
const tenantB = "tenant-b";
const cutoff = "2026-11-13T12:00:00.000Z";

function mission(status: string, updatedAt: string): MissionListItem {
  return {
    mission_id: `${status}-${updatedAt}`,
    objective: status,
    status,
    scope_limits: [],
    allowed_actions: [],
    created_at: updatedAt,
    updated_at: updatedAt,
  };
}

afterEach(() => {
  localStorage.clear();
});

describe("mission history presentation cutoff", () => {
  it("is tenant-scoped and reversible browser state", () => {
    setMissionHistoryCutoff(tenantA, cutoff);

    expect(readMissionHistoryCutoff(tenantA)).toBe(cutoff);
    expect(readMissionHistoryCutoff(tenantB)).toBeNull();
    expect(missionHistoryCutoffStorageKey(tenantA)).not.toBe(missionHistoryCutoffStorageKey(tenantB));

    clearMissionHistoryCutoff(tenantA);
    expect(readMissionHistoryCutoff(tenantA)).toBeNull();
  });

  it("hides only terminal missions that ended before the cutoff", () => {
    const missions = [
      mission("completed", "2026-11-13T11:59:59.000Z"),
      mission("failed", "2026-11-13T11:00:00.000Z"),
      mission("cancelled", "2026-11-13T10:00:00.000Z"),
      mission("archived", "2026-11-13T09:00:00.000Z"),
      mission("completed", "2026-11-13T12:00:00.000Z"),
      mission("planned", "2026-11-13T09:00:00.000Z"),
      mission("running", "2026-11-13T09:00:00.000Z"),
      mission("paused", "2026-11-13T09:00:00.000Z"),
      mission("unknown", "2026-11-13T09:00:00.000Z"),
    ];

    expect(filterMissionHistoryForView(missions, cutoff).map((item) => item.status)).toEqual([
      "completed",
      "planned",
      "running",
      "paused",
      "unknown",
    ]);
  });

  it("fails open for invalid dates or cutoffs", () => {
    const historical = mission("completed", "not-a-date");

    expect(filterMissionHistoryForView([historical], "not-a-cutoff")).toEqual([historical]);
    expect(filterMissionHistoryForView([historical], cutoff)).toEqual([historical]);
  });
});
