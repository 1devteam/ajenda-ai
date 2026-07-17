import { bucketMissionStatus } from "../../dashboard/dashboardModel";

type StatusBadgeProps = {
  status: string;
  label?: string;
};

const STATUS_STYLES: Record<string, string> = {
  running: "bg-semantic-info/15 text-semantic-info border-semantic-info/30",
  planned: "bg-zinc-500/15 text-zinc-300 border-zinc-500/30",
  approved: "bg-zinc-500/15 text-zinc-300 border-zinc-500/30",
  queued: "bg-zinc-500/15 text-zinc-300 border-zinc-500/30",
  paused: "bg-semantic-warning/15 text-semantic-warning border-semantic-warning/30",
  completed: "bg-semantic-success/15 text-semantic-success border-semantic-success/30",
  failed: "bg-crimson/15 text-crimson-bright border-crimson/30",
  cancelled: "bg-os-surface-elevated text-zinc-400 border-os-border",
  canceled: "bg-os-surface-elevated text-zinc-400 border-os-border",
  archived: "bg-os-surface-elevated text-zinc-400 border-os-border",
  pending: "bg-semantic-warning/15 text-semantic-warning border-semantic-warning/30",
  other: "bg-os-surface-elevated text-zinc-400 border-os-border",
};

export default function StatusBadge({ status, label }: StatusBadgeProps) {
  const normalized = status.toLowerCase();
  // Prefer exact MissionState / review labels for badge color; fall back to bucket.
  const style =
    STATUS_STYLES[normalized] ??
    STATUS_STYLES[bucketMissionStatus(status)] ??
    STATUS_STYLES.other;

  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-full border px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${style}`}
    >
      {label ?? status}
    </span>
  );
}