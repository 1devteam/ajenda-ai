import type { BrainCapabilityCheckResponse } from "../../types";
import type { BrainMissionTemplate } from "../../config/brainMissionTemplates";
import { pretty } from "../../utils/errors";

type BrainMissionsPanelProps = {
  templates: BrainMissionTemplate[];
  sessionReady: boolean;
  loading: boolean;
  capabilityReport: BrainCapabilityCheckResponse | null;
  onLaunch: (template: BrainMissionTemplate) => void;
  onCapabilityCheck: () => void;
};

export default function BrainMissionsPanel({
  templates,
  sessionReady,
  loading,
  capabilityReport,
  onLaunch,
  onCapabilityCheck,
}: BrainMissionsPanelProps) {
  return (
    <>
      <div className="panel-heading-row">
        <h2>Brain mission templates</h2>
        <button
          type="button"
          className="ghost-button"
          disabled={!sessionReady || loading}
          onClick={onCapabilityCheck}
        >
          Run capability check
        </button>
      </div>
      <p className="muted">
        Ten outcome-first missions for the Ajenda central brain. Credentials are optional — internal pipeline
        writes work without HubSpot.
      </p>
      <div className="card-grid two-up">
        {templates.map((template) => (
          <button
            className="proof-card"
            key={template.missionId}
            type="button"
            onClick={() => onLaunch(template)}
            disabled={!sessionReady || loading}
          >
            <strong>
              {template.missionId}: {template.title}
            </strong>
            <span>{template.description}</span>
            <small className="muted">{template.tier}</small>
          </button>
        ))}
      </div>
      {capabilityReport ? (
        <div className="result-grid capability-report">
          <div>
            <h3>Capability summary</h3>
            <pre>
              {pretty({
                charter_source: capabilityReport.charter_source,
                profile_ready: capabilityReport.profile_ready,
                summary: capabilityReport.summary,
              })}
            </pre>
          </div>
          <div>
            <h3>Mission readiness</h3>
            <pre>
              {pretty(
                capabilityReport.missions.map((item) => ({
                  id: item.mission_id,
                  status: item.status,
                  note: item.note,
                })),
              )}
            </pre>
          </div>
        </div>
      ) : null}
    </>
  );
}