import { useEffect, useMemo, useState } from "react";
import {
  createCheckout,
  createPortal,
  getTaskStatus,
  launchProof,
  launchTask,
  listActions,
} from "./api/client";
import type {
  AbilityAction,
  AbilityTaskCreate,
  AbilityTaskQueuedResponse,
  AbilityTaskStatusResponse,
  ApiFailure,
  RuntimeConfig,
} from "./types";

const DEFAULT_CONFIG: RuntimeConfig = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? "",
  tenantId: import.meta.env.VITE_DEFAULT_TENANT_ID ?? "00000000-0000-0000-0000-000000000001",
  apiKey: "",
};

const STORAGE_KEY = "ajenda.runtime.config.v1";

function loadConfig(): RuntimeConfig {
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return DEFAULT_CONFIG;
  }

  try {
    return { ...DEFAULT_CONFIG, ...JSON.parse(raw) };
  } catch {
    return DEFAULT_CONFIG;
  }
}

function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function failureText(error: unknown): string {
  const maybe = error as Partial<ApiFailure>;
  if (typeof maybe.status === "number") {
    return `${maybe.message ?? "Request failed"}\n${pretty(maybe.body)}`;
  }

  if (error instanceof Error) {
    return error.message;
  }

  return pretty(error);
}

const PROOF_BUTTONS = [
  {
    key: "calendar-read",
    title: "Calendar Read",
    description: "Runs calendar.read through worker tool.invoke.",
  },
  {
    key: "calendar-create",
    title: "Calendar Create",
    description: "Runs calendar.create_event with runtime side-effect authority.",
  },
  {
    key: "sales-qualify",
    title: "Sales Qualify",
    description: "Runs sales.qualify against a roofing lead payload.",
  },
  {
    key: "sales-draft-followup",
    title: "Sales Draft",
    description: "Runs sales.draft_followup through worker tool.invoke.",
  },
] as const;

const DEFAULT_CUSTOM_TASK = {
  action: "sales.qualify",
  input: {
    lead: {
      company: "Blackvault Roofing",
      role: "Owner",
      intent: "Needs roofing lead generation",
      email: "owner@example.com",
    },
    context: {
      intent: "Find more roofing leads",
    },
  },
  title: "Qualify roofing lead",
  mission_objective: "Qualify lead from runtime console.",
};

export default function App() {
  const [config, setConfig] = useState<RuntimeConfig>(() => loadConfig());
  const [actions, setActions] = useState<AbilityAction[]>([]);
  const [selectedPlan, setSelectedPlan] = useState<"starter" | "pro">("starter");
  const [customJson, setCustomJson] = useState<string>(pretty(DEFAULT_CUSTOM_TASK));
  const [activeTaskId, setActiveTaskId] = useState<string>("");
  const [taskStatus, setTaskStatus] = useState<AbilityTaskStatusResponse | null>(null);
  const [lastQueued, setLastQueued] = useState<AbilityTaskQueuedResponse | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string>("");
  const [notice, setNotice] = useState<string>("");

  const canCallApi = useMemo(() => {
    return config.tenantId.trim() && config.apiKey.trim();
  }, [config]);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
  }, [config]);

  useEffect(() => {
    if (!activeTaskId || !canCallApi) {
      return;
    }

    let cancelled = false;

    async function poll() {
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
  }, [activeTaskId, canCallApi, config]);

  async function runAction<T>(label: string, callback: () => Promise<T>): Promise<T | null> {
    setLoading(label);
    setError("");
    setNotice("");

    try {
      const result = await callback();
      return result;
    } catch (err) {
      setError(failureText(err));
      return null;
    } finally {
      setLoading(null);
    }
  }

  async function handleLoadActions() {
    const response = await runAction("Loading actions", () => listActions(config));
    if (response) {
      setActions(response.actions);
      setNotice(`Loaded ${response.actions.length} runtime action(s).`);
    }
  }

  async function handleProof(proof: (typeof PROOF_BUTTONS)[number]["key"]) {
    const queued = await runAction(`Launching ${proof}`, () => launchProof(config, proof));
    if (queued) {
      setLastQueued(queued);
      setActiveTaskId(queued.task_id);
      setNotice(`Queued ${queued.action}: ${queued.task_id}`);
    }
  }

  async function handleCustomLaunch() {
    let payload: AbilityTaskCreate;

    try {
      payload = JSON.parse(customJson) as AbilityTaskCreate;
    } catch (err) {
      setError(`Custom task JSON is invalid: ${failureText(err)}`);
      return;
    }

    const queued = await runAction("Launching custom task", () => launchTask(config, payload));
    if (queued) {
      setLastQueued(queued);
      setActiveTaskId(queued.task_id);
      setNotice(`Queued ${queued.action}: ${queued.task_id}`);
    }
  }

  async function handleCheckout() {
    const response = await runAction("Creating checkout", () => createCheckout(config, selectedPlan));
    if (response) {
      window.open(response.checkout_url, "_blank", "noopener,noreferrer");
      setNotice("Checkout session created and opened.");
    }
  }

  async function handlePortal() {
    const response = await runAction("Creating billing portal", () => createPortal(config));
    if (response) {
      window.open(response.portal_url, "_blank", "noopener,noreferrer");
      setNotice("Billing portal session created and opened.");
    }
  }

  return (
    <main className="app-shell">
      <section className="hero">
        <div>
          <p className="eyebrow">Ajenda AI</p>
          <h1>Runtime Ability Console</h1>
          <p>
            Launch worker-backed abilities, watch task state, inspect lineage/evidence,
            and test billing routes from one product surface.
          </p>
        </div>
        <div className="status-card">
          <span className={canCallApi ? "status-dot ok" : "status-dot bad"} />
          <div>
            <strong>{canCallApi ? "Configured" : "Needs API key"}</strong>
            <small>Tenant-scoped backend calls require X-Tenant-Id and X-Api-Key.</small>
          </div>
        </div>
      </section>

      <section className="grid two">
        <div className="panel">
          <h2>Runtime Config</h2>
          <label>
            API Base URL
            <input
              value={config.apiBaseUrl}
              onChange={(event) => setConfig({ ...config, apiBaseUrl: event.target.value })}
              placeholder="blank uses Vite proxy; or http://localhost:8000"
            />
          </label>
          <label>
            Tenant ID
            <input
              value={config.tenantId}
              onChange={(event) => setConfig({ ...config, tenantId: event.target.value })}
              placeholder="00000000-0000-0000-0000-000000000001"
            />
          </label>
          <label>
            API Key
            <input
              value={config.apiKey}
              onChange={(event) => setConfig({ ...config, apiKey: event.target.value })}
              placeholder="key_id.secret"
              type="password"
            />
          </label>
          <button onClick={handleLoadActions} disabled={!canCallApi || loading !== null}>
            Load Runtime Actions
          </button>
        </div>

        <div className="panel">
          <h2>Billing</h2>
          <label>
            Plan
            <select
              value={selectedPlan}
              onChange={(event) => setSelectedPlan(event.target.value as "starter" | "pro")}
            >
              <option value="starter">Starter</option>
              <option value="pro">Pro</option>
            </select>
          </label>
          <div className="button-row">
            <button onClick={handleCheckout} disabled={!canCallApi || loading !== null}>
              Create Checkout
            </button>
            <button onClick={handlePortal} disabled={!canCallApi || loading !== null}>
              Open Portal
            </button>
          </div>
        </div>
      </section>

      <section className="panel">
        <h2>Proof Launchers</h2>
        <div className="card-grid">
          {PROOF_BUTTONS.map((proof) => (
            <button
              className="proof-card"
              key={proof.key}
              onClick={() => void handleProof(proof.key)}
              disabled={!canCallApi || loading !== null}
            >
              <strong>{proof.title}</strong>
              <span>{proof.description}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="grid two">
        <div className="panel">
          <h2>Custom Worker Task</h2>
          <textarea
            value={customJson}
            onChange={(event) => setCustomJson(event.target.value)}
            spellCheck={false}
          />
          <button onClick={handleCustomLaunch} disabled={!canCallApi || loading !== null}>
            Launch Custom Task
          </button>
        </div>

        <div className="panel">
          <h2>Available Actions</h2>
          {actions.length === 0 ? (
            <p className="muted">Load actions after entering tenant/API key.</p>
          ) : (
            <div className="action-list">
              {actions.map((action) => (
                <div className="action-row" key={action.name}>
                  <div>
                    <strong>{action.name}</strong>
                    <small>
                      {action.provider} · {action.side_effect_class} · {action.provider_mode}
                    </small>
                  </div>
                  {action.requires_authority ? (
                    <span className="pill">authority</span>
                  ) : (
                    <span className="pill soft">read</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="panel">
        <h2>Task Monitor</h2>
        <div className="task-input-row">
          <input
            value={activeTaskId}
            onChange={(event) => setActiveTaskId(event.target.value)}
            placeholder="Task ID"
          />
          <button
            onClick={async () => {
              if (!activeTaskId) {
                return;
              }
              const response = await runAction("Refreshing task", () => getTaskStatus(config, activeTaskId));
              if (response) {
                setTaskStatus(response);
              }
            }}
            disabled={!canCallApi || !activeTaskId || loading !== null}
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
              <pre>{pretty({
                task_id: taskStatus.task_id,
                mission_id: taskStatus.mission_id,
                action: taskStatus.action,
                status: taskStatus.status,
              })}</pre>
            </div>
            <div>
              <h3>Lineage</h3>
              <pre>{pretty(taskStatus.lineage)}</pre>
            </div>
            <div>
              <h3>Evidence</h3>
              <pre>{pretty(taskStatus.evidence)}</pre>
            </div>
            <div>
              <h3>Audit</h3>
              <pre>{pretty(taskStatus.audit)}</pre>
            </div>
          </div>
        ) : (
          <p className="muted">Launch a proof or paste a task ID.</p>
        )}
      </section>

      {loading ? <div className="toast">Working: {loading}</div> : null}
      {notice ? <div className="toast ok-toast">{notice}</div> : null}
      {error ? (
        <div className="error-panel">
          <strong>Error</strong>
          <pre>{error}</pre>
        </div>
      ) : null}
    </main>
  );
}
