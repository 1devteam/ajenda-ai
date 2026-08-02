import { Link } from "react-router";
import type { ReviewQueueItem } from "../../types";
import { pendingReviewItems } from "../../dashboard/dashboardModel";
import Card from "../primitives/Card";
import StatusBadge from "../ui/StatusBadge";
import EmptyState from "../ui/EmptyState";
import PanelSkeleton from "../states/PanelSkeleton";
import ErrorState from "../states/ErrorState";
import Button from "../primitives/Button";

type ApprovalsPanelProps = {
  items: ReviewQueueItem[];
  total: number;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
};

export default function ApprovalsPanel({
  items,
  total,
  loading = false,
  error = null,
  onRetry,
}: ApprovalsPanelProps) {
  const pending = pendingReviewItems(items);

  return (
    <Card elevated className="@container flex min-h-[280px] flex-col">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-lg font-semibold text-zinc-100">Approvals</h2>
          <p className="mt-1 text-sm text-zinc-500">
            {total > 0
              ? `${total} waiting for you`
              : "Nothing waiting for review"}
          </p>
        </div>
        <Link
          to="/approvals"
          className="cc-focus-ring text-sm font-medium text-semantic-info hover:underline"
        >
          Open queue
        </Link>
      </div>

      {loading ? (
        <PanelSkeleton rows={3} />
      ) : error ? (
        <ErrorState title="Could not load approvals" description={error} onRetry={onRetry} />
      ) : pending.length === 0 ? (
        <EmptyState
          icon="✓"
          title="All clear"
          description="When work needs your review, it shows up here."
          action={
            <Link to="/approvals">
              <Button variant="ghost">Go to approvals</Button>
            </Link>
          }
        />
      ) : (
        <div className="flex flex-col gap-2 @md:gap-3" role="list">
          {pending.slice(0, 5).map((item) => (
            <Link
              key={item.artifact_id}
              to="/approvals"
              className="cc-focus-ring group flex min-h-12 items-center justify-between gap-3 rounded-lg border border-os-border bg-os-bg/40 px-3 py-3 transition-colors hover:border-zinc-600 hover:bg-os-surface-elevated/50 @md:px-4"
              role="listitem"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-zinc-100">{item.artifact_type}</p>
                <p className="truncate text-xs text-zinc-500">{item.artifact_id}</p>
              </div>
              <StatusBadge status={item.review_status} label="Pending" />
            </Link>
          ))}
        </div>
      )}
    </Card>
  );
}
