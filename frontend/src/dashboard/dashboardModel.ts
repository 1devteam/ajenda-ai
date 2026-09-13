import type { CrmRecordItem, MissionListItem, ReviewQueueItem } from "../types";

export type MissionStatusBucket = "planned" | "running" | "completed" | "failed";

export type StatusBreakdown = Record<MissionStatusBucket, number>;

export type WorkflowView = "all" | "crm" | "gtm" | "vertical";

/** Keep CRM records scoped to the operator's selected workflow context. */
export function filterRecordsByWorkflow(
  records: CrmRecordItem[],
  workflowView: WorkflowView,
): CrmRecordItem[] {
  if (workflowView === "all") {
    return records;
  }
  return records.filter(
    (item) => String(item.data.workflow_context || "crm") === workflowView,
  );
}

export type PrimaryAction = {
  id: "approvals" | "setup" | "launch";
  label: string;
  to: string;
};

export type AttentionBanner =
  | { id: "quota"; severity: "blocking" | "warning"; message: string; to: string; cta: string }
  | { id: "setup"; severity: "warning"; message: string; to: string; cta: string }
  | { id: "email"; severity: "warning"; message: string; to: string; cta: string };

export type ChecklistStepId = "setup" | "connect" | "launch";

export type ChecklistStep = {
  id: ChecklistStepId;
  label: string;
  description: string;
  to: string;
  done: boolean;
};

/**
 * Map backend `MissionState` values onto the four dashboard buckets.
 * Source of truth: backend/domain/enums.py MissionState.
 *
 * - planned: non-terminal work not currently executing (includes approved/queued/paused)
 * - running: actively executing
 * - completed / failed: terminal outcomes
 * - cancelled / archived: terminal but not failures — excluded from failed counts
 */
const RUNNING_STATES = new Set(["running"]);
const PLANNED_STATES = new Set(["planned", "approved", "queued", "paused"]);
const COMPLETED_STATES = new Set(["completed"]);
const FAILED_STATES = new Set(["failed"]);
/** Terminal states that must not inflate Failed metrics. */
const NON_FAILURE_TERMINAL = new Set(["cancelled", "canceled", "archived"]);

export function bucketMissionStatus(status: string): MissionStatusBucket | "other" {
  const normalized = status.trim().toLowerCase();
  if (RUNNING_STATES.has(normalized)) {
    return "running";
  }
  if (PLANNED_STATES.has(normalized)) {
    return "planned";
  }
  if (COMPLETED_STATES.has(normalized)) {
    return "completed";
  }
  if (FAILED_STATES.has(normalized)) {
    return "failed";
  }
  if (NON_FAILURE_TERMINAL.has(normalized)) {
    return "other";
  }
  return "other";
}

/** Active = non-terminal missions still on the operator radar. */
export function isActiveMission(mission: MissionListItem): boolean {
  // Paused missions remain available in history and review queues, but do not
  // belong in the live-work rotation after runtime reconciliation.
  if (mission.status.trim().toLowerCase() === "paused") {
    return false;
  }
  const bucket = bucketMissionStatus(mission.status);
  return bucket === "planned" || bucket === "running";
}

export function countStatusBreakdown(missions: MissionListItem[]): StatusBreakdown {
  const counts: StatusBreakdown = { planned: 0, running: 0, completed: 0, failed: 0 };
  for (const mission of missions) {
    const bucket = bucketMissionStatus(mission.status);
    if (bucket !== "other") {
      counts[bucket] += 1;
    }
  }
  return counts;
}

export function countCompletedToday(missions: MissionListItem[], now = new Date()): number {
  const today = now.toDateString();
  return missions.filter((mission) => {
    if (bucketMissionStatus(mission.status) !== "completed") {
      return false;
    }
    return new Date(mission.updated_at).toDateString() === today;
  }).length;
}

export function successRateLabel(missions: MissionListItem[]): string {
  if (missions.length === 0) {
    return "—";
  }
  const completed = countStatusBreakdown(missions).completed;
  return `${Math.round((completed / missions.length) * 100)}%`;
}

export function usagePercent(current: number, limit: number): number | null {
  if (limit < 0 || limit === 0) {
    return null;
  }
  return Math.round((current / limit) * 100);
}

export function resolvePrimaryAction(input: {
  pendingApprovals: number;
  wizardDone: boolean;
  emailVerified: boolean;
}): PrimaryAction {
  if (input.pendingApprovals > 0) {
    return {
      id: "approvals",
      label:
        input.pendingApprovals === 1
          ? "Review 1 approval"
          : `Review ${input.pendingApprovals} approvals`,
      to: "/approvals",
    };
  }
  if (!input.wizardDone || !input.emailVerified) {
    return {
      id: "setup",
      label: input.emailVerified ? "Finish setup" : "Finish setup",
      to: input.emailVerified ? "/setup" : "/verify-email",
    };
  }
  return { id: "launch", label: "Launch mission", to: "/missions" };
}

/** One banner only. Priority: quota → setup → email. */
export function resolveAttentionBanner(input: {
  quotaPct: number | null;
  wizardDone: boolean;
  emailVerified: boolean;
}): AttentionBanner | null {
  if (input.quotaPct !== null && input.quotaPct >= 80) {
    return {
      id: "quota",
      severity: input.quotaPct >= 100 ? "blocking" : "warning",
      message: `API usage at ${input.quotaPct}% this month`,
      to: "/billing",
      cta: "Open billing",
    };
  }
  if (!input.wizardDone) {
    return {
      id: "setup",
      severity: "warning",
      message: "Finish business memory setup so missions know your context",
      to: "/setup",
      cta: "Open setup",
    };
  }
  if (!input.emailVerified) {
    return {
      id: "email",
      severity: "warning",
      message: "Verify your email to unlock full workspace access",
      to: "/verify-email",
      cta: "Verify email",
    };
  }
  return null;
}

export function buildOnboardingChecklist(input: {
  wizardDone: boolean;
  hasConnections: boolean;
  hasLaunchedMission: boolean;
}): ChecklistStep[] {
  return [
    {
      id: "setup",
      label: "Finish setup",
      description: "Business memory and workspace basics",
      to: "/setup",
      done: input.wizardDone,
    },
    {
      id: "connect",
      label: "Connect tools",
      description: "Credentials for email, CRM, and other providers",
      to: "/connections",
      done: input.hasConnections,
    },
    {
      id: "launch",
      label: "Launch first mission",
      description: "Turn a goal into governed work",
      to: "/missions",
      done: input.hasLaunchedMission,
    },
  ];
}

export function checklistIncomplete(steps: ChecklistStep[]): boolean {
  return steps.some((step) => !step.done);
}

export function pendingReviewItems(items: ReviewQueueItem[]): ReviewQueueItem[] {
  return items.filter((item) => item.review_status.toLowerCase() === "pending");
}
