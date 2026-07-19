import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
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

const PLACEHOLDER =
  "Research roofing companies in Austin, identify three strong prospects, draft personalized introductions, and bring them to me before anything is sent.";

export default function MissionsPage() {
  const { session } = useAuth();
  const navigate = useNavigate();
  const [instruction, setInstruction] = useState("");
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);
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
      setSelectedTemplateId(null);
      await refreshMissions();
      // Composition creates plan + graph; execution continues on the mission page.
      navigate(`/missions/${result.mission_id}`);
    } catch (err) {
      setError(err);
    } finally {
      setConfirming(false);
    }
  }

  return (
    <main>
      <PageHeader
        eyebrow="Missions"
        title="Request a mission"
        lead="You describe the outcome. Ajenda classifies the work, chooses skills from its full catalog, plans the order, and executes under your charter. You never pick tools."
      />

      <section className="panel">
        <h2>Templates</h2>
        <p className="muted">Optional starters. They only fill the request box — they do not choose skills.</p>
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

      <section className="panel callout">
        <h2>What makes a mission executable</h2>
        <ul>
          <li>
            <strong>Outcome</strong> — what success looks like (who, market, deliverable).
          </li>
          <li>
            <strong>Scope</strong> — industry, place, or count when it matters (e.g. “three prospects in Austin”).
          </li>
          <li>
            <strong>Hard limits</strong> — especially send vs draft (e.g. “bring them to me before anything is
            sent”).
          </li>
          <li>
            <strong>Connections</strong> — optional; Ajenda reports missing links and will not fake success.{" "}
            <Link to="/credentials">Manage connections</Link>
          </li>
        </ul>
        <p className="muted">
          Skills are always available to Ajenda. Your operating charter still blocks forbidden actions (for example
          send-by-default stays off until you opt in).
        </p>
      </section>

      <section className="panel">
        <form className="form-grid mission-create-form" onSubmit={(event) => void handleCompose(event)}>
          <label>
            Mission request
            <textarea
              className="mission-textarea"
              value={instruction}
              onChange={(event) => {
                setInstruction(event.target.value);
                setSelectedTemplateId(null);
                setProposal(null);
                setConfirmed(null);
              }}
              placeholder={PLACEHOLDER}
              rows={5}
              required
            />
          </label>

          <div className="mission-card-actions">
            <button type="submit" className="primary-button" disabled={!session || loading || !instruction.trim()}>
              {loading ? "Planning…" : "Plan mission"}
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
                <li key={step.step_key}>{step.title}</li>
              ))}
            </ol>
            <p className="field-hint">
              Ajenda selected these steps from its full skill catalog for this outcome. You do not configure skills
              here.
            </p>
          </div>

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
              <strong>Clarify to improve the plan</strong>
              <ul>
                {proposal.clarifications.map((item) => (
                  <li key={`${item.field}-${item.question}`}>{item.question}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {proposal.forbidden_actions.includes("gtm.email_send") ? (
            <p className="muted">
              <strong>Send is off</strong> for this mission (charter). Drafts stay in review until you allow sending.
            </p>
          ) : null}

          <div className="mission-card-actions">
            <button
              type="button"
              className="primary-button"
              disabled={!session || confirming || !proposal.ready_to_start}
              onClick={() => void handleConfirm()}
            >
              {confirming ? "Starting…" : "Start mission"}
            </button>
            <button
              type="button"
              className="ghost-button"
              disabled={loading}
              onClick={() => {
                setProposal(null);
              }}
            >
              Revise request
            </button>
          </div>
          {!proposal.ready_to_start ? (
            <p className="field-hint">
              Not ready yet — resolve connections or clarify the request, then plan again.
            </p>
          ) : null}
        </section>
      ) : null}

      {confirmed ? (
        <section className="panel success-panel">
          <h2>Mission created</h2>
          <p>
            Mission <code>{confirmed.mission_id}</code> is ready. Opening execution…
          </p>
          <Link className="action-link" to={`/missions/${confirmed.mission_id}`}>
            Continue to execution
          </Link>
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
          <p className="muted">No missions yet. Use a template or write a request above.</p>
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
