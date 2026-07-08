import type { ReviewQueueItem } from "../../types";
import { pretty } from "../../utils/errors";
import StatusBadge from "./StatusBadge";
import EmptyState from "./EmptyState";

type ApprovalReviewPanelProps = {
  item: ReviewQueueItem | null;
  loading: boolean;
  onApprove: (artifactId: string) => void;
  onDecline?: (artifactId: string) => void;
};

export default function ApprovalReviewPanel({
  item,
  loading,
  onApprove,
  onDecline,
}: ApprovalReviewPanelProps) {
  if (!item) {
    return (
      <div className="panel">
        <EmptyState
          title="Select an approval"
          description="Choose a pending item to preview content and take action."
        />
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-heading-row">
        <div>
          <h2>{item.artifact_type}</h2>
          <p className="muted">
            <code>{item.artifact_id}</code>
          </p>
        </div>
        <StatusBadge status={item.review_status} label="Needs review" />
      </div>

      <section>
        <h3>Preview</h3>
        <pre>{pretty(item.content)}</pre>
      </section>

      <div className="button-row">
        {onDecline ? (
          <button
            type="button"
            className="ghost-button"
            disabled={loading}
            onClick={() => onDecline(item.artifact_id)}
          >
            Decline
          </button>
        ) : null}
        <button
          type="button"
          className="primary-button"
          disabled={loading}
          onClick={() => onApprove(item.artifact_id)}
        >
          Approve for send
        </button>
      </div>
      <p className="muted">
        Approvals are recorded through Ajenda governance. Side-effecting actions still require
        explicit authorization at send time.
      </p>
    </div>
  );
}