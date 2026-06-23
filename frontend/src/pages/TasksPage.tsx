import { useEffect, useMemo, useState } from "react";
import { getTaskStatus, launchProof } from "../api/client";
import { loadSession, sessionToRuntimeConfig } from "../auth/session";
import type { AbilityTaskQueuedResponse, AbilityTaskStatusResponse } from "../types";
import { failureText, pretty } from "../utils/errors";

const PROOF_BUTTONS = [
  { key: "calendar-read" as const, title: "Calendar Read", description: "Read-only calendar proof." },
  { key: "sales-qualify" as const, title: "Sales Qualify", description: "Qualify a sample roofing lead." },
] as const;

export default function TasksPage() {
  const session = loadSession();
  const config = useMemo(
    () => (session ? sessionToRuntimeConfig(session) : null),
    [session?.tenantId, session?.apiKey],
  );
  const [activeTaskId, setActiveTaskId] = useState("");
  const [taskStatus, setTaskStatus] = useState<AbilityTaskStatusResponse | null>(null);
  const [lastQueued, setLastQueued] = useState<AbilityTaskQueuedResponse | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!activeTaskId || !config) {
      return;
    }

    let cancelled = false;

    async function poll() {
      if (!config) return;
      try {
        const status = await getTaskStatus(config, activeTaskId);
        if (!cancelled) {
          setTaskStatus(status);
        }
      } catch (err) {
        if (!cancelled) {
          setError(failureText(err));
        }
      }
    }

    void poll();
    const timer = window.setInterval(() => {
      void poll();
    }, 2500);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeTaskId, config]);

  async function handleProof(proof: (typeof PROOF_BUTTONS)[number]["key"]) {
    if (!config) return;
    setLoading(`Launching ${proof}`);
    setError("");
    try {
      const queued = await launchProof(config, proof);
      setLastQueued(queued);
      setActiveTaskId(queued.task_id);
    } catch (err) {
      setError(failureText(err));
    } finally {
      setLoading(null);
    }
  }

  return (
    <main className="page-shell">
      <section className="hero compact-hero">
        <div>
          <p className="eyebrow">Runtime tasks</p>
          <h1>Launch worker proofs</h1>
          <p>Queue ability-runtime tasks and monitor status, lineage, and evidence from your tenant session.</p>
        </div>
      </section>

      <section className="panel">
        <h2>Proof launchers</h2>
        <div className="card-grid two-up">
          {PROOF_BUTTONS.map((proof) => (
            <button
              className="proof-card"
              key={proof.key}
              type="button"
              onClick={() => void handleProof(proof.key)}
              disabled={!config || loading !== null}
            >
              <strong>{proof.title}</strong>
              <span>{proof.description}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="panel">
        <h2>Task monitor</h2>
        <div className="task-input-row">
          <input
            value={activeTaskId}
            onChange={(event) => setActiveTaskId(event.target.value)}
            placeholder="Task ID"
          />
          <button
            type="button"
            onClick={async () => {
              if (!config || !activeTaskId) return;
              setLoading("Refreshing task");
              try {
                setTaskStatus(await getTaskStatus(config, activeTaskId));
              } catch (err) {
                setError(failureText(err));
              } finally {
                setLoading(null);
              }
            }}
            disabled={!config || !activeTaskId || loading !== null}
          >
            Refresh
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

      {loading ? <div className="toast">Working: {loading}</div> : null}
      {error ? (
        <div className="inline-error">
          <pre>{error}</pre>
        </div>
      ) : null}
    </main>
  );
}
