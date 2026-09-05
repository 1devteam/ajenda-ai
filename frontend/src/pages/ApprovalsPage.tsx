import { useCallback, useEffect, useState } from "react";
import { approveReviewQueueItem, approveTaskReview, listPendingTaskApprovals, listReviewQueue } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import PageErrorAlert from "../components/PageErrorAlert";
import PageHeader from "../components/ui/PageHeader";
import ApprovalReviewPanel from "../components/ui/ApprovalReviewPanel";
import LoadingState from "../components/ui/LoadingState";
import StatusBadge from "../components/ui/StatusBadge";
import type { ReviewQueueItem } from "../types";

export default function ApprovalsPage() {
  const { session } = useAuth();
  const [queue, setQueue] = useState<ReviewQueueItem[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const refresh = useCallback(async () => {
    if (!session) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [pending, taskApprovals] = await Promise.all([
        listReviewQueue(session, { status: "pending", limit: 50 }),
        listPendingTaskApprovals(session),
      ]);
      const tasks = taskApprovals.items.map((item) => ({ ...item, approval_kind: "task" as const, artifact_id: item.task_id ?? item.artifact_id }));
      const combined = [...pending.items, ...tasks];
      setQueue(combined);
      if (!selectedId && combined[0]?.artifact_id) {
        setSelectedId(combined[0].artifact_id);
      }
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [session, selectedId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const selected = queue.find((item) => item.artifact_id === selectedId) ?? null;

  async function handleApprove(artifactId: string) {
    if (!session) {
      return;
    }
    setActionLoading(true);
    setError(null);
    try {
      const item = queue.find((candidate) => candidate.artifact_id === artifactId);
      if (item?.approval_kind === "task") {
        await approveTaskReview(session, artifactId);
      } else {
        await approveReviewQueueItem(session, artifactId);
      }
      setQueue((current) => current.filter((item) => item.artifact_id !== artifactId));
      setSelectedId("");
    } catch (err) {
      setError(err);
    } finally {
      setActionLoading(false);
    }
  }

  return (
    <main>
      <PageHeader
        eyebrow="Governance"
        title="Approvals"
        lead="Review drafts and outbound actions before Ajenda proceeds. Nothing sends without your explicit approval."
        actions={
          <button type="button" className="ghost-button" disabled={loading} onClick={() => void refresh()}>
            Refresh
          </button>
        }
      />

      {loading && queue.length === 0 ? <LoadingState label="Loading pending approvals..." /> : null}

      <div className="cc-split">
        <div className="cc-list-panel">
          <div className="cc-list-panel-header">Pending ({queue.length})</div>
          {queue.length === 0 ? (
            <div className="cc-empty">No items waiting for approval.</div>
          ) : (
            queue.map((item) => (
              <button
                key={item.artifact_id}
                type="button"
                className={`cc-list-item${selectedId === item.artifact_id ? " selected" : ""}`}
                onClick={() => setSelectedId(item.artifact_id)}
              >
                <strong>{item.artifact_type}</strong>
                <div>
                  <StatusBadge status="pending_review" label="Review needed" />
                </div>
                <small className="muted">{item.artifact_id}</small>
              </button>
            ))
          )}
        </div>

        <ApprovalReviewPanel
          item={selected}
          loading={actionLoading}
          onApprove={handleApprove}
        />
      </div>

      <PageErrorAlert error={error} />
    </main>
  );
}
