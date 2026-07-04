import type { BrainMissionCapstoneStep, BrainMissionTemplate } from "../../config/brainMissionTemplates";
import type { ReviewQueueItem } from "../../types";
import { pretty } from "../../utils/errors";

type ReviewQueuePanelProps = {
  reviewQueue: ReviewQueueItem[];
  approvedArtifacts: ReviewQueueItem[];
  activeCapstone: BrainMissionTemplate | null;
  selectedSendArtifactId: string;
  sessionReady: boolean;
  loading: boolean;
  onRefresh: () => void;
  onApprove: (artifactId: string) => void;
  onCapstoneStep: (step: BrainMissionCapstoneStep) => void;
  onCloseCapstone: () => void;
  onSelectSendArtifact: (artifactId: string) => void;
};

export default function ReviewQueuePanel({
  reviewQueue,
  approvedArtifacts,
  activeCapstone,
  selectedSendArtifactId,
  sessionReady,
  loading,
  onRefresh,
  onApprove,
  onCapstoneStep,
  onCloseCapstone,
  onSelectSendArtifact,
}: ReviewQueuePanelProps) {
  return (
    <>
      <div className="panel-heading-row">
        <h3>Draft review queue</h3>
        <button type="button" className="ghost-button" disabled={!sessionReady || loading} onClick={onRefresh}>
          Refresh queue
        </button>
      </div>
      {activeCapstone?.capstoneSteps ? (
        <div className="panel capstone-panel">
          <div className="panel-heading-row">
            <h3>{activeCapstone.missionId} — Capstone guide</h3>
            <button type="button" className="ghost-button" onClick={onCloseCapstone}>
              Close
            </button>
          </div>
          <p className="muted">{activeCapstone.description}</p>
          <div className="card-grid two-up">
            {activeCapstone.capstoneSteps.map((step) => (
              <div className="proof-card static-card" key={step.step}>
                <strong>
                  {step.step}. {step.label}
                </strong>
                <span>{step.description}</span>
                <button
                  type="button"
                  className="primary-button"
                  disabled={!sessionReady || loading}
                  onClick={() => onCapstoneStep(step)}
                >
                  {step.action === "review_queue" ? "Refresh queue" : `Run ${step.action}`}
                </button>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {reviewQueue.length > 0 ? (
        <div className="card-grid two-up">
          {reviewQueue.map((item) => (
            <div className="proof-card static-card" key={item.artifact_id}>
              <strong>{item.artifact_type}</strong>
              <span>
                <code>{item.artifact_id}</code>
              </span>
              <pre>{pretty(item.content)}</pre>
              <button
                type="button"
                className="primary-button"
                disabled={!sessionReady || loading}
                onClick={() => onApprove(item.artifact_id)}
              >
                Approve for send
              </button>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">No pending drafts. Launch M7 or M8, then refresh the queue.</p>
      )}

      {approvedArtifacts.length > 0 ? (
        <div className="approved-artifact-row">
          <label>
            Approved artifact for send
            <select value={selectedSendArtifactId} onChange={(event) => onSelectSendArtifact(event.target.value)}>
              {approvedArtifacts.map((item) => (
                <option key={item.artifact_id} value={item.artifact_id}>
                  {item.artifact_type} — {item.artifact_id}
                </option>
              ))}
            </select>
          </label>
        </div>
      ) : null}
    </>
  );
}