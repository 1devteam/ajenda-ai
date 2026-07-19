import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  composeMission,
  confirmMissionComposition,
  listMissions,
} from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import PageErrorAlert from "../components/PageErrorAlert";
import PageHeader from "../components/ui/PageHeader";
import { LAUNCH_MISSION_TEMPLATES } from "../config/launchMissionTemplates";
import type {
  MissionComposeConfirmResponse,
  MissionComposeResponse,
  MissionListItem,
} from "../types";

const EXAMPLE_INSTRUCTION =
  "Research roofing companies in Austin, identify three strong prospects, draft personalized introductions, and bring them to me before anything is sent.";

function humanizeAction(action: string): string {
  const labels: Record<string, string> = {
    "web.research": "Web research",
    "web.search": "Web search",
    "sales.research": "Sales research",
    "sales.qualify": "Qualify prospects",
    "sales.score_lead": "Score leads",
    "gtm.lead_enrich": "Enrich contacts",
    "gtm.email_draft": "Draft introductions",
    "gtm.email_send": "Send email",
    "crm.research": "CRM research",
    "google_calendar.events_read": "Read calendar",
    "record.search": "Search records",
    "retrieval.hybrid_search": "Search memory",
  };
  return labels[action] ?? action;
}

export default function MissionsPage() {
  const { session } = useAuth();
  const [instruction, setInstruction] = useState("");
  const [selectedTemplateId, setSelectedTemplateId] = useState("custom");
  const [proposal, setProposal] = useState<MissionComposeResponse | null>(null);
  const [confirmed, setConfirmed] = useState<MissionComposeConfirmResponse | null>(null);
  const [missions, setMissions] = useState<MissionListItem[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [listError, setListError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [listLoading, setListLoading] = useState(false);

  const refreshMissions = useCallback(async () => {
    if (!session) {
      setMissions([]);
      return;
    }
    setListLoading(true);
    setListError(null);
    try {
      const response = await listMissions(session, { limit: 50 });
      setMissions(response.missions);
    } catch (err) {
      setListError(err);
    } finally {
      setListLoading(false);
    }
  }, [session]);

  useEffect(() => {
    void refreshMissions();
  }, [refreshMissions]);

  function applyTemplate(templateId: string) {
    const template = LAUNCH_MISSION_TEMPLATES.find((item) => item.id === templateId);
    if (!template) {
      return;
    }
    setSelectedTemplateId(templateId);
    setInstruction(template.instruction);
    setProposal(null);
    setConfirmed(null);
    setError(null);
  }

  async function handleCompose(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) {
      return;
    }
    const text = instruction.trim();
    if (!text) {
      return;
    }

    setLoading(true);
    setError(null);
    setProposal(null);
    setConfirmed(null);
    try {
      const result = await composeMission(session, { instruction: text });
      setProposal(result);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }

  async function handleConfirm() {
    if (!session || !proposal) {
      return;
    }
    setConfirming(true);
    setError(null);
    try {
      const result = await confirmMissionComposition(session, proposal.proposal_id, {
        composition: proposal.composition,
      });
      setConfirmed(result);
      setProposal(null);
      setInstruction("");
      await refreshMissions();
    } catch (err) {
      setError(err);
    } finally {
      setConfirming(false);
    }
  }

  const readySelections =
    proposal?.selected_abilities.filter(
      (item) => item.selection_status === "selected" && item.readiness === "ready",
    ) ?? [];

  return (
    <main>
      <PageHeader
        eyebrow="Launch mission"
        title="Tell Ajenda what to accomplish"
        lead="Describe the outcome in plain language. Ajenda chooses the work, the abilities, and the order — you review the plan, then start. You do not pick tools."
      />

      <section className="panel">
        <h2>Suggestions</h2>
        <p className="muted">Optional starters. They fill the mission box — they do not lock abilities.</p>
        <div className="cc-template-grid">
          {LAUNCH_MISSION_TEMPLATES.map((template) => (
            <button
              key={template.id}
              type="button"
              className={`cc-template-card${selectedTemplateId === template.id ? " selected" : ""}`}
              onClick={() => applyTemplate(template.id)}
            >
              <h3>{template.title}</h3>
              <p>{template.description}</p>
            </button>
          ))}
        </div>
      </section>

      <section className="panel">
        <form className="form-grid mission-create-form" onSubmit={(event) => void handleCompose(event)}>
          <label>
            What should Ajenda do?
            <textarea
              className="mission-textarea"
              value={instruction}
              onChange={(event) => {
                setInstruction(event.target.value);
                setProposal(null);
                setConfirmed(null);
              }}
              placeholder={EXAMPLE_INSTRUCTION}
              rows={5}
              required
            />
            <span className="field-hint">
              Include who, what, and any hard limits (for example “draft only — do not send”). Ajenda builds the
              plan and only uses abilities that fit that instruction and your operating charter.
            </span>
          </label>

          <div className="mission-card-actions">
            <button type="submit" className="primary-button" disabled={!session || loading || !instruction.trim()}>
              {loading ? "Planning…" : "Plan mission"}
            </button>
            <button
              type="button"
              className="ghost-button"
              onClick={() => {
                setInstruction(EXAMPLE_INSTRUCTION);
                setSelectedTemplateId("roofing-example");
                setProposal(null);
                setConfirmed(null);
              }}
            >
              Use Austin roofing example
            </button>
          </div>
        </form>
      </section>

      {proposal ? (
        <section className="panel">
          <h2>Ajenda’s plan</h2>
          <p className="mission-card-objective">{proposal.mission_brief.objective}</p>

          {proposal.mission_brief.success_criteria.length > 0 ? (
            <div className="mission-card-meta">
              <strong>Success looks like</strong>
              <ul>
                {proposal.mission_brief.success_criteria.map((item) => (
                  <li key={item.description}>{item.description}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {proposal.mission_brief.constraints.length > 0 ? (
            <p className="mission-card-meta">
              <strong>Limits:</strong> {proposal.mission_brief.constraints.join("; ")}
            </p>
          ) : null}

          <div className="mission-card-meta">
            <strong>Work Ajenda will run</strong>
            <ol>
              {proposal.planned_steps.map((step) => (
                <li key={step.step_key}>
                  {step.title}
                  <span className="muted"> — {humanizeAction(step.action_name)}</span>
                </li>
              ))}
            </ol>
          </div>

          {readySelections.length > 0 ? (
            <p className="field-hint">
              Abilities are selected automatically from Ajenda’s governed catalog for this outcome. Everyday
              operators do not choose tools; the runtime envelope is set by this plan.
            </p>
          ) : null}

          {proposal.missing_connections.length > 0 ? (
            <div className="callout">
              <strong>Connections that would improve this mission</strong>
              <ul>
                {proposal.missing_connections.map((item) => (
                  <li key={`${String(item.provider)}-${String(item.action)}`}>
                    {String(item.provider ?? "connection")}: {String(item.message ?? "not connected")}
                  </li>
                ))}
              </ul>
              <p className="muted">
                Missing connections are reported — Ajenda will not fake success.{" "}
                <Link to="/credentials">Manage connections</Link>
              </p>
            </div>
          ) : null}

          {proposal.clarifications.length > 0 ? (
            <div className="callout">
              <strong>Clarifications that would help</strong>
              <ul>
                {proposal.clarifications.map((item) => (
                  <li key={`${item.field}-${item.question}`}>{item.question}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {proposal.forbidden_actions.includes("gtm.email_send") ? (
            <p className="muted">
              <strong>Send is off</strong> for this mission. Drafts stay in review until you explicitly allow
              sending in a later mission or charter change.
            </p>
          ) : null}

          <div className="mission-card-actions">
            <button
              type="button"
              className="primary-button"
              disabled={!session || confirming || !proposal.ready_to_start}
              onClick={() => void handleConfirm()}
            >
              {confirming ? "Creating mission…" : "Start mission"}
            </button>
            <button
              type="button"
              className="ghost-button"
              disabled={loading}
              onClick={() => {
                setProposal(null);
              }}
            >
              Revise instruction
            </button>
          </div>
          {!proposal.ready_to_start ? (
            <p className="field-hint">
              This plan is not ready yet — add missing connections or clarify the instruction, then plan again.
            </p>
          ) : null}
        </section>
      ) : null}

      {confirmed ? (
        <section className="panel success-panel">
          <h2>Mission ready</h2>
          <p>
            Mission <code>{confirmed.mission_id}</code> is created with plan and task graph. Runtime work still
            starts only through the governed dispatch path — nothing was auto-sent or auto-queued outside that
            ladder.
          </p>
          <div className="mission-card-actions">
            <Link className="action-link" to={`/missions/${confirmed.mission_id}`}>
              Open mission
            </Link>
            <Link className="ghost-link" to="/missions">
              Back to list
            </Link>
          </div>
        </section>
      ) : null}

      <section className="panel">
        <div className="panel-heading-row">
          <h2>Your missions</h2>
          <button
            type="button"
            className="ghost-button"
            disabled={!session || listLoading}
            onClick={() => void refreshMissions()}
          >
            {listLoading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
        {missions.length === 0 ? (
          <p className="muted">No missions yet. Describe an outcome above.</p>
        ) : (
          <ul className="mission-list">
            {missions.map((mission) => (
              <li className="mission-card" key={mission.mission_id}>
                <div className="mission-card-header">
                  <span className={`status-pill status-${mission.status}`}>{mission.status}</span>
                  <time dateTime={mission.created_at}>{new Date(mission.created_at).toLocaleString()}</time>
                </div>
                <p className="mission-card-objective">{mission.objective}</p>
                {mission.scope_limits.length > 0 ? (
                  <p className="mission-card-meta">
                    <strong>Scope:</strong> {mission.scope_limits.join("; ")}
                  </p>
                ) : null}
                {mission.allowed_actions.length > 0 ? (
                  <p className="mission-card-meta">
                    <strong>Ajenda’s plan:</strong> {mission.allowed_actions.map(humanizeAction).join(" → ")}
                  </p>
                ) : null}
                <div className="mission-card-actions">
                  <Link className="action-link" to={`/missions/${mission.mission_id}`}>
                    Open mission
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        )}
        <PageErrorAlert error={listError} className="inline-error compact-error" />
      </section>

      <PageErrorAlert error={error} />
    </main>
  );
}
