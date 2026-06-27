import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { createMission, listMissions } from "../api/client";
import { loadSession, sessionToRuntimeConfig } from "../auth/session";
import { MISSION_ALLOWED_ACTION_OPTIONS } from "../config/missionAbilities";
import type { MissionIntakeQualityViolation, MissionListItem, MissionReadResponse } from "../types";
import { failureText } from "../utils/errors";

const MISSION_PROMPT_GUIDE = {
  summary:
    "Describe a concrete business outcome in plain language. Include who, what, and how you will know it worked.",
  exampleObjective:
    "Find three qualified roofing leads in Austin and draft personalized greeting emails for each prospect.",
  exampleCriterion:
    "Three leads are documented with company name, contact email, and qualification notes ready for outreach.",
  rejectedExamples: ["do something", "help me", "be successful", "make it work"],
  exampleScope: "Austin metro roofing segment, three leads, greeting-email deliverables",
  defaultAllowedActions: ["gtm.lead_enrich", "gtm.email_draft", "crm.research", "gtm.email_check"],
};

const DEFAULT_OBJECTIVE = "";
const DEFAULT_CRITERION = "";

function parseQualityViolations(error: unknown): MissionIntakeQualityViolation[] {
  const maybe = error as { body?: { detail?: unknown } };
  const detail = maybe.body?.detail;
  if (typeof detail !== "object" || detail === null) {
    return [];
  }
  if (
    "code" in detail &&
    detail.code === "MISSION_INTAKE_QUALITY_DENIED" &&
    "violations" in detail &&
    Array.isArray(detail.violations)
  ) {
    return detail.violations as MissionIntakeQualityViolation[];
  }
  return [];
}

export default function MissionsPage() {
  const session = loadSession();
  const config = useMemo(
    () => (session ? sessionToRuntimeConfig(session) : null),
    [session?.tenantId, session?.apiKey, session?.accessToken],
  );
  const [objective, setObjective] = useState(DEFAULT_OBJECTIVE);
  const [successCriterion, setSuccessCriterion] = useState(DEFAULT_CRITERION);
  const [scopeLimit, setScopeLimit] = useState("");
  const [allowedActions, setAllowedActions] = useState<string[]>(MISSION_PROMPT_GUIDE.defaultAllowedActions);
  const [missions, setMissions] = useState<MissionListItem[]>([]);
  const [createdMission, setCreatedMission] = useState<MissionReadResponse | null>(null);
  const [violations, setViolations] = useState<MissionIntakeQualityViolation[]>([]);
  const [error, setError] = useState("");
  const [listError, setListError] = useState("");
  const [loading, setLoading] = useState(false);
  const [listLoading, setListLoading] = useState(false);

  const refreshMissions = useCallback(async () => {
    if (!config) {
      setMissions([]);
      return;
    }
    setListLoading(true);
    setListError("");
    try {
      const response = await listMissions(config, { limit: 50 });
      setMissions(response.missions);
    } catch (err) {
      setListError(failureText(err));
    } finally {
      setListLoading(false);
    }
  }, [config]);

  useEffect(() => {
    void refreshMissions();
  }, [refreshMissions]);

  function applyExample() {
    setObjective(MISSION_PROMPT_GUIDE.exampleObjective);
    setSuccessCriterion(MISSION_PROMPT_GUIDE.exampleCriterion);
    setScopeLimit(MISSION_PROMPT_GUIDE.exampleScope);
    setAllowedActions([...MISSION_PROMPT_GUIDE.defaultAllowedActions]);
    setViolations([]);
    setError("");
  }

  function toggleAllowedAction(action: string) {
    setAllowedActions((current) =>
      current.includes(action) ? current.filter((item) => item !== action) : [...current, action],
    );
  }

  async function handleCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!config) {
      return;
    }

    setLoading(true);
    setError("");
    setViolations([]);
    setCreatedMission(null);

    try {
      const mission = await createMission(config, {
        objective: objective.trim(),
        success_criteria: [
          {
            description: successCriterion.trim(),
            evidence: ["lead research summary", "draft email artifacts"],
          },
        ],
        scope_limits: scopeLimit.trim() ? [scopeLimit.trim()] : [],
        allowed_actions: allowedActions,
      });
      setCreatedMission(mission);
      await refreshMissions();
      setObjective("");
      setSuccessCriterion("");
      setScopeLimit("");
    } catch (err) {
      const qualityViolations = parseQualityViolations(err);
      if (qualityViolations.length > 0) {
        setViolations(qualityViolations);
      }
      setError(failureText(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="page-shell narrow">
      <section className="hero compact-hero">
        <div>
          <p className="eyebrow">Missions</p>
          <h1>Start with an outcome</h1>
          <p>
            Missions turn business goals into governed work. Vague prompts are rejected — be specific about what should
            happen and how you will measure success.
          </p>
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading-row">
          <h2>Your missions</h2>
          <button type="button" className="ghost-button" disabled={!config || listLoading} onClick={() => void refreshMissions()}>
            {listLoading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
        {missions.length === 0 ? (
          <p className="muted">No missions yet. Create your first outcome below.</p>
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
                    <strong>Abilities:</strong> {mission.allowed_actions.join(", ")}
                  </p>
                ) : null}
                <Link className="action-link" to={`/tasks?mission_id=${mission.mission_id}`}>
                  Launch abilities
                </Link>
              </li>
            ))}
          </ul>
        )}
        {listError ? (
          <div className="inline-error compact-error">
            <pre>{listError}</pre>
          </div>
        ) : null}
      </section>

      <section className="panel">
        <div className="callout mission-example-callout">
          <strong>Acceptable mission example</strong>
          <p className="muted">{MISSION_PROMPT_GUIDE.summary}</p>
          <dl className="mission-example-list">
            <div>
              <dt>Objective</dt>
              <dd>{MISSION_PROMPT_GUIDE.exampleObjective}</dd>
            </div>
            <div>
              <dt>Success criterion</dt>
              <dd>{MISSION_PROMPT_GUIDE.exampleCriterion}</dd>
            </div>
          </dl>
          <p className="field-hint">
            Avoid vague prompts like {MISSION_PROMPT_GUIDE.rejectedExamples.map((item) => `"${item}"`).join(", ")}.
          </p>
          <button type="button" className="ghost-button" onClick={applyExample}>
            Use this example
          </button>
        </div>

        <form className="form-grid mission-create-form" onSubmit={(event) => void handleCreate(event)}>
          <label>
            Mission objective
            <textarea
              className="mission-textarea"
              value={objective}
              onChange={(event) => setObjective(event.target.value)}
              placeholder={MISSION_PROMPT_GUIDE.exampleObjective}
              rows={4}
              required
            />
            <span className="field-hint">State the outcome Ajenda should accomplish — not a question or placeholder.</span>
          </label>

          <label>
            Success criterion
            <textarea
              className="mission-textarea"
              value={successCriterion}
              onChange={(event) => setSuccessCriterion(event.target.value)}
              placeholder={MISSION_PROMPT_GUIDE.exampleCriterion}
              rows={3}
              required
            />
            <span className="field-hint">
              Describe how you will verify completion — counts, deliverables, or documented evidence.
            </span>
          </label>

          <label>
            Scope limit
            <input
              value={scopeLimit}
              onChange={(event) => setScopeLimit(event.target.value)}
              placeholder={MISSION_PROMPT_GUIDE.exampleScope}
            />
            <span className="field-hint">Bound the mission with region, segment, timeframe, or audience.</span>
          </label>

          <fieldset className="ability-scope-fieldset">
            <legend>Allowed abilities for this mission</legend>
            <div className="ability-scope-grid">
              {MISSION_ALLOWED_ACTION_OPTIONS.map((item) => (
                <label className="ability-scope-option" key={item.action}>
                  <input
                    type="checkbox"
                    checked={allowedActions.includes(item.action)}
                    onChange={() => toggleAllowedAction(item.action)}
                  />
                  <span>{item.label}</span>
                  <small>{item.action}</small>
                </label>
              ))}
            </div>
          </fieldset>

          <button type="submit" disabled={!config || loading}>
            {loading ? "Creating mission…" : "Create mission"}
          </button>
        </form>
      </section>

      {violations.length > 0 ? (
        <section className="panel">
          <h2>Fix these before resubmitting</h2>
          <ul className="violation-list">
            {violations.map((item) => (
              <li key={`${item.field}-${item.code}`}>
                <strong>{item.field}</strong>
                <span>{item.reason}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {createdMission ? (
        <section className="panel success-panel">
          <h2>Mission created</h2>
          <p>
            <code>{createdMission.mission_id}</code> is <strong>{createdMission.status}</strong> and ready for
            mission-scoped abilities.
          </p>
          <Link className="action-link" to={`/tasks?mission_id=${createdMission.mission_id}`}>
            Launch mission-scoped abilities
          </Link>
        </section>
      ) : null}

      {error ? (
        <div className="inline-error">
          <pre>{error}</pre>
        </div>
      ) : null}
    </main>
  );
}