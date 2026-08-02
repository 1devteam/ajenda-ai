import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";
import {
  composeMission,
  confirmMissionComposition,
  listMissions,
} from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import PageErrorAlert from "../components/PageErrorAlert";
import PageHeader from "../components/ui/PageHeader";
import type {
  MissionComposeConfirmResponse,
  MissionComposeResponse,
  MissionListItem,
} from "../types";
import { newIdempotencyKey } from "../utils/errors";

const PLACEHOLDER =
  "Research roofing companies in Austin, identify three strong prospects, draft personalized introductions, and bring them to me before anything is sent.";

export default function MissionsPage() {
  const { session } = useAuth();
  const navigate = useNavigate();
  const [instruction, setInstruction] = useState("");
  const [interpretationThreadId, setInterpretationThreadId] = useState<string | null>(null);
  const [proposal, setProposal] = useState<MissionComposeResponse | null>(null);
  const [confirmed, setConfirmed] = useState<MissionComposeConfirmResponse | null>(null);
  const [missions, setMissions] = useState<MissionListItem[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [listError, setListError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [listLoading, setListLoading] = useState(false);
  // Stable per-proposal key so confirm retries do not create duplicate missions.
  const [confirmIdempotencyKey, setConfirmIdempotencyKey] = useState<string | null>(null);

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

  async function handleCompose(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) {
      return;
    }
    // Validate non-empty with trim; send original textarea value unchanged.
    if (!instruction.trim()) {
      return;
    }

    setLoading(true);
    setError(null);
    setProposal(null);
    setConfirmed(null);
    setConfirmIdempotencyKey(null);
    try {
      const result = await composeMission(session, {
        instruction,
        interpretation_thread_id: interpretationThreadId ?? undefined,
      });
      setProposal(result);
      // One UUID v4 per proposal; reused on confirm retries (middleware requires UUID).
      setConfirmIdempotencyKey(newIdempotencyKey());
      if (result.interpretation_thread_id) {
        setInterpretationThreadId(result.interpretation_thread_id);
      }
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
    const idempotencyKey = confirmIdempotencyKey ?? newIdempotencyKey();
    if (!confirmIdempotencyKey) {
      setConfirmIdempotencyKey(idempotencyKey);
    }
    try {
      // Proposal-ID confirmation — backend revalidates server-side.
      // Reuse the same idempotency key across retries for this proposal.
      const result = await confirmMissionComposition(session, proposal.proposal_id, {
        idempotency_key: idempotencyKey,
      });
      setConfirmed(result);
      setProposal(null);
      setInstruction("");
      setInterpretationThreadId(null);
      setConfirmIdempotencyKey(null);
      await refreshMissions();
      // Composition creates plan + graph; open execution and auto-run remaining ladder.
      navigate(`/missions/${result.mission_id}?execute=1`);
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
        title="Plan a mission"
        lead="Describe what you want Ajenda to accomplish. Be clear about the outcome, who or what it involves, and what the finished work should contain."
      />

      <section className={`cc-mission-workspace${proposal ? " has-brief" : ""}`}>
        <div className="cc-mission-conversation">
          <div className="cc-conversation-intro">
            <span className="cc-ai-mark">A</span>
            <div>
              <strong>What should we accomplish?</strong>
              <p>
                Tell me naturally. I&apos;ll turn the request into a governed plan. If material information is missing,
                I&apos;ll tell you what to include when you restate the complete mission.
              </p>
            </div>
          </div>
        <form className="form-grid mission-create-form" onSubmit={(event) => void handleCompose(event)}>
          <label>
            <span className="sr-only">Mission request</span>
            <textarea
              className="mission-textarea"
              value={instruction}
              onChange={(event) => {
                setInstruction(event.target.value);
                setProposal(null);
                setConfirmed(null);
              }}
              placeholder={PLACEHOLDER}
              rows={4}
              required
            />
          </label>

          <div className="cc-composer-actions">
            <span>Enter the details Ajenda needs to define success.</span>
            <button type="submit" className="primary-button" disabled={!session || loading || !instruction.trim()}>
              {loading ? "Planning…" : "Plan mission"}
            </button>
          </div>
        </form>
        <PageErrorAlert error={error} />
        </div>

      {proposal ? (
        <aside className="cc-mission-brief">
          <p className="cc-section-kicker">Mission brief</p>
          <h2>{proposal.clarifications.length > 0 ? "Needs clarity" : "Ready to review"}</h2>
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
            <div className="cc-clarification">
              <strong>Restate the complete mission</strong>
              <ul>
                {proposal.clarifications.map((item) => (
                  <li key={`${item.field}-${item.question}`}>{item.question}</li>
                ))}
              </ul>
              <p>
                Do not send a short fragment alone. Rewrite the full mission in the box on the left,
                include every missing detail above, then plan again. Ajenda will not merge partial
                answers into the previous plan.
              </p>
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
              Not ready yet — resolve connections or restate the complete mission with the missing
              detail, then plan again.
            </p>
          ) : null}
        </aside>
      ) : null}
      </section>

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

      <section className="cc-mission-index" id="running">
        <div className="panel-heading-row">
          <div>
            <p className="cc-section-kicker">Mission activity</p>
            <h2>Recent missions</h2>
          </div>
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
                  <span id={mission.status === "planned" ? "staged" : mission.status === "completed" ? "history" : undefined} className={`status-pill status-${mission.status}`}>{mission.status === "planned" ? "staged" : mission.status}</span>
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

    </main>
  );
}
