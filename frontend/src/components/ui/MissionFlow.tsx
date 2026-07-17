import type { StatusBreakdown } from "../../dashboard/dashboardModel";
import PanelSkeleton from "../states/PanelSkeleton";
import EmptyState from "./EmptyState";
import ErrorState from "../states/ErrorState";

export type FlowStep = {
  id: string;
  label: string;
  count: number;
};

type MissionFlowProps = {
  breakdown?: StatusBreakdown;
  /** @deprecated Prefer `breakdown` for data-driven status counts. */
  steps?: FlowStep[];
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
};

const STATUS_ORDER: Array<{ id: keyof StatusBreakdown; label: string }> = [
  { id: "planned", label: "Planned" },
  { id: "running", label: "Running" },
  { id: "completed", label: "Completed" },
  { id: "failed", label: "Failed" },
];

function toSteps(breakdown?: StatusBreakdown, steps?: FlowStep[]): FlowStep[] {
  if (breakdown) {
    return STATUS_ORDER.map((item) => ({
      id: item.id,
      label: item.label,
      count: breakdown[item.id],
    }));
  }
  return steps ?? [];
}

export default function MissionFlow({
  breakdown,
  steps,
  loading = false,
  error = null,
  onRetry,
}: MissionFlowProps) {
  const resolved = toSteps(breakdown, steps);

  if (loading) {
    return (
      <div className="@container" aria-busy="true">
        <PanelSkeleton rows={2} compact />
      </div>
    );
  }

  if (error) {
    return (
      <ErrorState title="Status unavailable" description={error} onRetry={onRetry} />
    );
  }

  if (resolved.every((step) => step.count === 0)) {
    return (
      <EmptyState
        icon="◎"
        title="No mission activity yet"
        description="Launch a mission to see planned, running, completed, and failed work here."
      />
    );
  }

  return (
    <>
      <div
        className="hidden gap-2 @lg:grid @lg:grid-cols-4"
        role="list"
        aria-label="Mission status"
      >
        {resolved.map((step) => {
          const emphasize = step.id === "failed" && step.count > 0;
          const running = step.id === "running" && step.count > 0;
          return (
            <div
              key={step.id}
              role="listitem"
              className={`rounded-lg border px-3 py-3 @md:px-4 ${
                emphasize
                  ? "border-crimson/40 bg-crimson/10"
                  : running
                    ? "border-semantic-info/30 bg-semantic-info/5"
                    : "border-os-border bg-os-bg/50"
              }`}
            >
              <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                {step.label}
              </p>
              <p className="mt-2 font-display text-2xl font-semibold text-zinc-50">{step.count}</p>
            </div>
          );
        })}
      </div>

      <div className="flex flex-col gap-2 @lg:hidden" role="list" aria-label="Mission status">
        {resolved.map((step) => {
          const emphasize = step.id === "failed" && step.count > 0;
          return (
            <div
              key={step.id}
              role="listitem"
              className={`flex min-h-12 items-center justify-between rounded-lg border px-4 py-3 ${
                emphasize ? "border-crimson/40 bg-crimson/10" : "border-os-border bg-os-bg/50"
              }`}
            >
              <span className="text-sm font-medium text-zinc-200">{step.label}</span>
              <span className="font-display text-lg font-semibold text-zinc-50">{step.count}</span>
            </div>
          );
        })}
      </div>
    </>
  );
}
