import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { createMission } from "../api/client";
import { loadSession, sessionToRuntimeConfig } from "../auth/session";
import type { MissionIntakeQualityViolation, MissionReadResponse } from "../types";
import { failureText, pretty } from "../utils/errors";

const MISSION_PROMPT_GUIDE = {
  summary:
    "Describe a concrete business outcome in plain language. Include who, what, and how you will know it worked.",
  exampleObjective:
    "Find three qualified roofing leads in Austin and draft personalized greeting emails for each prospect.",
  exampleCriterion:
    "Three leads are documented with company name, contact email, and qualification notes ready for outreach.",
  rejectedExamples: ["do something", "help me", "be successful", "make it work"],
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
  const [createdMission, setCreatedMission] = useState<MissionReadResponse | null>(null);
  const [violations, setViolations] = useState<MissionIntakeQualityViolation[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  function applyExample() {
    setObjective(MISSION_PROMPT_GUIDE.exampleObjective);
    setSuccessCriterion(MISSION_PROMPT_GUIDE.exampleCriterion);
    setViolations([]);
    setError("");
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
            evidence: ["lead research summary"],
          },
        ],
      });
      setCreatedMission(mission);
      setObjective("");
      setSuccessCriterion("");
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
        <section className="panel">
          <h2>Mission created</h2>
          <p>
            Mission <code>{createdMission.mission_id}</code> is planned and ready for the next bridge stages.
          </p>
          <pre>{pretty(createdMission)}</pre>
          <Link className="action-link" to="/tasks">
            Launch runtime tasks for this workspace
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