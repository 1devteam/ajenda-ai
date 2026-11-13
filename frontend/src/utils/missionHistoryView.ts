import type { MissionListItem } from "../types";

const STORAGE_PREFIX = "ajenda.missionHistoryView";

/**
 * Mission records, evidence, and approvals remain server-owned. This key
 * stores only one browser's reversible presentation cutoff for a tenant.
 */
export function missionHistoryCutoffStorageKey(tenantId: string): string {
  return `${STORAGE_PREFIX}.${tenantId}.terminalCutoff`;
}

export function readMissionHistoryCutoff(tenantId: string): string | null {
  try {
    const cutoff = localStorage.getItem(missionHistoryCutoffStorageKey(tenantId));
    return cutoff && Number.isFinite(Date.parse(cutoff)) ? cutoff : null;
  } catch {
    return null;
  }
}

export function setMissionHistoryCutoff(tenantId: string, cutoff: string): boolean {
  try {
    localStorage.setItem(missionHistoryCutoffStorageKey(tenantId), cutoff);
    return true;
  } catch {
    // A storage failure must not hide mission history or affect runtime data.
    return false;
  }
}

export function clearMissionHistoryCutoff(tenantId: string): boolean {
  try {
    localStorage.removeItem(missionHistoryCutoffStorageKey(tenantId));
    return true;
  } catch {
    return false;
  }
}

/**
 * Only these canonical terminal mission states may be hidden by the local
 * presentation preference. Paused missions may be waiting on review and must
 * remain visible; unknown statuses fail open.
 */
export function isTerminalMissionStatus(status: string): boolean {
  return new Set(["completed", "failed", "cancelled", "canceled", "archived"]).has(
    status.trim().toLowerCase(),
  );
}

export function filterMissionHistoryForView(
  missions: MissionListItem[],
  cutoff: string | null,
): MissionListItem[] {
  if (!cutoff) {
    return missions;
  }
  const cutoffTimestamp = Date.parse(cutoff);
  if (!Number.isFinite(cutoffTimestamp)) {
    return missions;
  }
  return missions.filter((mission) => {
    if (!isTerminalMissionStatus(mission.status)) {
      return true;
    }
    const updatedTimestamp = Date.parse(mission.updated_at);
    return !Number.isFinite(updatedTimestamp) || updatedTimestamp >= cutoffTimestamp;
  });
}
