import { Link } from "react-router-dom";
import StatusBadge from "./StatusBadge";
import PanelSkeleton from "../states/PanelSkeleton";

type MissionCardProps = {
  missionId: string;
  title: string;
  status: string;
  meta?: string;
  loading?: boolean;
};

export default function MissionCard({
  missionId,
  title,
  status,
  meta,
  loading = false,
}: MissionCardProps) {
  if (loading) {
    return (
      <div className="rounded-lg border border-os-border bg-os-bg/40 p-3" aria-busy="true">
        <PanelSkeleton rows={1} compact />
      </div>
    );
  }

  return (
    <Link
      to={`/missions/${missionId}`}
      className="cc-focus-ring block rounded-lg border border-os-border bg-os-bg/40 px-3 py-3 transition-colors hover:border-zinc-600 hover:bg-os-surface-elevated/60 @md:px-4"
    >
      <div className="flex items-start justify-between gap-3">
        <strong className="line-clamp-2 text-sm font-medium text-zinc-100">{title}</strong>
        <StatusBadge status={status} />
      </div>
      {meta ? <p className="mt-2 text-xs text-zinc-500">{meta}</p> : null}
    </Link>
  );
}
