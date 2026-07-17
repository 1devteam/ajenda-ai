import { Link } from "react-router-dom";
import type { MissionListItem } from "../../types";
import { isActiveMission } from "../../dashboard/dashboardModel";
import Card from "../primitives/Card";
import MissionCard from "../ui/MissionCard";
import EmptyState from "../ui/EmptyState";
import PanelSkeleton from "../states/PanelSkeleton";
import ErrorState from "../states/ErrorState";
import Button from "../primitives/Button";

type ActiveWorkPanelProps = {
  missions: MissionListItem[];
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  onLaunch?: () => void;
};

export default function ActiveWorkPanel({
  missions,
  loading = false,
  error = null,
  onRetry,
  onLaunch,
}: ActiveWorkPanelProps) {
  const active = missions.filter(isActiveMission);

  return (
    <Card elevated className="@container flex min-h-[280px] flex-col">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-lg font-semibold text-zinc-100">Active work</h2>
          <p className="mt-1 text-sm text-zinc-500">Missions planned or running.</p>
        </div>
        <Link
          to="/active-work"
          className="cc-focus-ring text-sm font-medium text-semantic-info hover:underline"
        >
          View all
        </Link>
      </div>

      {loading ? (
        <PanelSkeleton rows={3} />
      ) : error ? (
        <ErrorState title="Could not load active work" description={error} onRetry={onRetry} />
      ) : active.length === 0 ? (
        <EmptyState
          icon="◎"
          title="No active missions"
          description="Launch a mission to see work appear here."
          action={
            onLaunch ? (
              <Button variant="primary" onClick={onLaunch}>
                Launch mission
              </Button>
            ) : undefined
          }
        />
      ) : (
        <div className="flex flex-col gap-2 @md:gap-3" role="list">
          {active.slice(0, 5).map((mission) => (
            <MissionCard
              key={mission.mission_id}
              missionId={mission.mission_id}
              title={mission.objective}
              status={mission.status}
              meta={new Date(mission.updated_at).toLocaleString()}
            />
          ))}
        </div>
      )}
    </Card>
  );
}
