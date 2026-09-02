import type { AbilityTaskQueuedResponse, AbilityTaskStatusResponse } from "../../types";
import { pretty } from "../../utils/errors";

type TaskMonitorProps = {
  activeTaskId: string;
  lastQueued: AbilityTaskQueuedResponse | null;
  taskStatus: AbilityTaskStatusResponse | null;
  sessionReady: boolean;
  loading: boolean;
  onTaskIdChange: (taskId: string) => void;
  onRefresh: () => void;
  onCancel: () => void;
};

export default function TaskMonitor({
  activeTaskId,
  lastQueued,
  taskStatus,
  sessionReady,
  loading,
  onTaskIdChange,
  onRefresh,
  onCancel,
}: TaskMonitorProps) {
  return (
    <section className="panel">
      <h2>Task monitor</h2>
      <div className="task-input-row">
        <input
          value={activeTaskId}
          onChange={(event) => onTaskIdChange(event.target.value)}
          placeholder="Task ID"
        />
        <button
          type="button"
          onClick={onRefresh}
          disabled={!sessionReady || !activeTaskId || loading}
        >
          Refresh
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={!sessionReady || !activeTaskId || loading || ["completed", "failed", "cancelled", "blocked", "dead_lettered"].includes(taskStatus?.status ?? "")}
        >
          Stop task
        </button>
      </div>

      {lastQueued ? (
        <div className="queued">
          Last queued: <strong>{lastQueued.action}</strong> · {lastQueued.task_id}
        </div>
      ) : null}

      {taskStatus ? (
        <div className="result-grid">
          <div>
            <h3>Status</h3>
            <pre>
              {pretty({
                task_id: taskStatus.task_id,
                mission_id: taskStatus.mission_id,
                action: taskStatus.action,
                status: taskStatus.status,
                failure: taskStatus.metadata_json?.failure ?? null,
                cancel_requested: taskStatus.metadata_json?.cancel_requested ?? false,
              })}
            </pre>
          </div>
          <div>
            <h3>Evidence</h3>
            <pre>{pretty(taskStatus.evidence)}</pre>
          </div>
        </div>
      ) : (
        <p className="muted">Launch a proof to start monitoring.</p>
      )}
    </section>
  );
}
