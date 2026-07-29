import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  admitMissionRuntimeQueue,
  admitMissionToRuntime,
  compileMission,
  createMissionPlan,
  getMissionDispatchReadiness,
  getMissionLifecycle,
  getMissionRuntimeReadiness,
  getTaskStatus,
  materializeMissionRuntimeTasks,
  provisionBridgeRuntimeAuthority,
} from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import PageErrorAlert from "../components/PageErrorAlert";
import type {
  AbilityTaskStatusResponse,
  BridgeRuntimeAuthorityReadResponse,
  MissionLifecycleReadResponse,
  RuntimeDispatchReadinessReadResponse,
  RuntimeReadinessReadResponse,
  RuntimeTaskMaterializationReadResponse,
} from "../types";
import {
  buildMissionPlanPayload,
  intakeAllowedActions,
  intakeSuccessCriteria,
  PIPELINE_STEPS,
} from "../utils/missionBridge";
import { failureText, pretty } from "../utils/errors";

type StepStatus = "pending" | "complete" | "blocked" | "running";

/** Prefer confirmed composition instruction over lossy mission.objective restatement. */
function compositionInstructionFromIntake(intake: Record<string, unknown> | null | undefined): string {
  if (!intake || typeof intake !== "object") {
    return "";
  }
  const context = intake.context;
  if (!context || typeof context !== "object") {
    return "";
  }
  const composition = (context as { composition?: unknown }).composition;
  if (!composition || typeof composition !== "object") {
    return "";
  }
  const instruction = (composition as { instruction?: unknown }).instruction;
  return typeof instruction === "string" ? instruction.trim() : "";
}

function formatCompileFailure(compiled: Record<string, unknown>): string {
  const status = String(compiled.compile_status ?? "unknown");
  const blockers = Array.isArray(compiled.blockers) ? compiled.blockers : [];
  const blockerMsgs = blockers
    .map((b) =>
      typeof b === "object" && b && "message" in b ? String((b as { message: string }).message) : "",
    )
    .filter(Boolean);
  const warnings = Array.isArray(compiled.warnings) ? compiled.warnings : [];
  const warningMsgs = warnings
    .map((w) =>
      typeof w === "object" && w && "message" in w ? String((w as { message: string }).message) : "",
    )
    .filter(Boolean);
  const parts = [...blockerMsgs];
  for (const msg of warningMsgs) {
    if (!parts.includes(msg)) {
      parts.push(msg);
    }
  }
  if (parts.length > 0) {
    return parts.join("; ");
  }
  return `Server compile is not ready (status=${status}).`;
}

function stepStatusFor(
  stepId: (typeof PIPELINE_STEPS)[number]["id"],
  lifecycle: MissionLifecycleReadResponse | null,
  extras: {
    readiness: RuntimeReadinessReadResponse | null;
    materialization: RuntimeTaskMaterializationReadResponse | null;
    dispatch: RuntimeDispatchReadinessReadResponse | null;
    authorities: BridgeRuntimeAuthorityReadResponse | null;
  },
): StepStatus {
  if (!lifecycle) {
    return "pending";
  }
  const completeness = lifecycle.completeness;
  switch (stepId) {
    case "plan":
      return completeness.has_plan ? "complete" : "pending";
    case "graph":
      return completeness.has_task_graph ? "complete" : "pending";
    case "materialize":
      return completeness.has_materialization ? "complete" : "pending";
    case "authority":
      return extras.authorities ? "complete" : "pending";
    case "admit":
      return completeness.has_runtime_admission ? "complete" : "pending";
    case "readiness":
      return extras.readiness?.ready ? "complete" : extras.readiness ? "blocked" : "pending";
    case "tasks":
      return extras.materialization?.materialization_status === "materialized" ? "complete" : "pending";
    case "queue":
      return extras.dispatch?.queued_task_count ? "complete" : "pending";
    default:
      return "pending";
  }
}

export default function MissionDispatchPage() {
  const { missionId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const { session } = useAuth();
  const autoExecuteStarted = useRef(false);

  const [lifecycle, setLifecycle] = useState<MissionLifecycleReadResponse | null>(null);
  const [readiness, setReadiness] = useState<RuntimeReadinessReadResponse | null>(null);
  const [taskMaterialization, setTaskMaterialization] = useState<RuntimeTaskMaterializationReadResponse | null>(null);
  const [dispatchReadiness, setDispatchReadiness] = useState<RuntimeDispatchReadinessReadResponse | null>(null);
  const [authorities, setAuthorities] = useState<BridgeRuntimeAuthorityReadResponse | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState("");
  const [monitoredTaskId, setMonitoredTaskId] = useState("");
  const [taskStatus, setTaskStatus] = useState<AbilityTaskStatusResponse | null>(null);

  const allowedActions = useMemo(() => intakeAllowedActions(lifecycle?.intake ?? null), [lifecycle?.intake]);
  const successCriteria = useMemo(() => intakeSuccessCriteria(lifecycle?.intake ?? null), [lifecycle?.intake]);

  const refreshLifecycle = useCallback(async () => {
    if (!session || !missionId) {
      return;
    }
    const response = await getMissionLifecycle(session, missionId);
    setLifecycle(response);
    return response;
  }, [session, missionId]);

  const refreshReadinessViews = useCallback(async () => {
    if (!session || !missionId) {
      return;
    }
    try {
      const [readinessResponse, dispatchResponse] = await Promise.all([
        getMissionRuntimeReadiness(session, missionId),
        getMissionDispatchReadiness(session, missionId),
      ]);
      setReadiness(readinessResponse);
      setDispatchReadiness(dispatchResponse);
    } catch (err) {
      setReadiness(null);
      setDispatchReadiness(null);
      setError(err);
    }
  }, [session, missionId]);

  useEffect(() => {
    if (!session) {
      return;
    }
    let cancelled = false;
    async function load() {
      try {
        const lifecycleResponse = await getMissionLifecycle(session!, missionId);
        if (!cancelled) {
          setLifecycle(lifecycleResponse);
        }
        await refreshReadinessViews();
      } catch (err) {
        if (!cancelled) {
          setError(err);
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [session, missionId, refreshReadinessViews]);

  useEffect(() => {
    if (!session || !monitoredTaskId) {
      return;
    }
    let cancelled = false;
    async function poll() {
      try {
        const status = await getTaskStatus(session!, monitoredTaskId);
        if (!cancelled) {
          setTaskStatus(status);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err);
        }
      }
    }
    void poll();
    const timer = window.setInterval(() => void poll(), 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [session, monitoredTaskId]);

  async function runStep(label: string, fn: () => Promise<void>) {
    setLoading(label);
    setError(null);
    setNotice("");
    try {
      await fn();
      await refreshLifecycle();
      await refreshReadinessViews();
    } catch (err) {
      setError(err);
    } finally {
      setLoading(null);
    }
  }

  async function handlePreparePlan() {
    if (!session || !lifecycle) {
      return;
    }
    await runStep("Creating plan…", async () => {
      await createMissionPlan(
        session,
        missionId,
        buildMissionPlanPayload(lifecycle.mission.objective, allowedActions, successCriteria),
      );
      setNotice("Mission plan created.");
    });
  }

  async function handlePrepareGraph() {
    if (!session) {
      return;
    }
    await runStep("Compiling task graph (server)…", async () => {
      // Omit instruction: server prefers stored composition.instruction over objective.
      const compiled = await compileMission(session, missionId, {
        persist: true,
        source: "mission_dispatch_ui",
      });
      const status = String(compiled.compile_status ?? "");
      const display = (compiled.display as { allowed_actions?: string[] } | undefined) ?? {};
      const actions = display.allowed_actions ?? [];
      if (status !== "ready") {
        throw new Error(formatCompileFailure(compiled));
      }
      setNotice(
        `Server compiled ${actions.length} ability step(s) via ajenda-mission-compiler.`,
      );
      await refreshLifecycle();
    });
  }

  async function handleMaterializeGraph() {
    if (!session) {
      return;
    }
    await runStep("Recompiling + materializing (server)…", async () => {
      // Server compile owns graph materialization; prefer stored composition instruction.
      const compiled = await compileMission(session, missionId, {
        persist: true,
        source: "mission_dispatch_ui",
      });
      if (String(compiled.compile_status ?? "") !== "ready") {
        throw new Error(formatCompileFailure(compiled));
      }
      setNotice("Server compile wrote graph materialization.");
      await refreshLifecycle();
    });
  }

  async function handleProvisionAuthority() {
    if (!session) {
      return;
    }
    await runStep("Provisioning runtime authority…", async () => {
      const response = await provisionBridgeRuntimeAuthority(session, missionId);
      setAuthorities(response);
      setNotice(`Provisioned authority for ${response.node_authorities.length} node(s).`);
    });
  }

  async function handleAdmitRuntime() {
    if (!session) {
      return;
    }
    await runStep("Admitting to runtime…", async () => {
      // Server derives selected_nodes from compiled graph + bridge authority.
      // Client does not invent node keys, capability IDs, or admission identity.
      const response = await admitMissionToRuntime(session, missionId, {
        admission_status: "admitted",
        auto_provision_authority: true,
      });
      const selected = (response.runtime_admission as { selected_nodes?: unknown[] } | undefined)
        ?.selected_nodes;
      const count = Array.isArray(selected) ? selected.length : 0;
      setNotice(`Graph admitted to runtime (${count} node(s), server-owned).`);
    });
  }

  async function handleCheckReadiness() {
    if (!session) {
      return;
    }
    await runStep("Checking readiness…", async () => {
      const response = await getMissionRuntimeReadiness(session, missionId);
      setReadiness(response);
      setNotice(response.ready ? "Runtime is ready for task materialization." : "Runtime readiness has blockers.");
    });
  }

  async function handleMaterializeTasks() {
    if (!session) {
      return;
    }
    await runStep("Materializing runtime tasks…", async () => {
      const response = await materializeMissionRuntimeTasks(session, missionId);
      setTaskMaterialization(response);
      if (response.created_execution_task_ids.length > 0) {
        setMonitoredTaskId(response.created_execution_task_ids[0]);
      }
      setNotice(`Materialized ${response.task_count} planned task(s).`);
    });
  }

  async function handleQueueAdmission() {
    if (!session) {
      return;
    }
    await runStep("Queueing tasks…", async () => {
      const response = await admitMissionRuntimeQueue(session, missionId);
      setNotice(`Queued ${response.queued_task_ids.length} task(s).`);
    });
  }

  async function handleRunPipeline() {
    if (!session) {
      return;
    }
    setLoading("Running full pipeline…");
    setError(null);
    setNotice("");
    try {
      let current = await refreshLifecycle();
      if (!current) {
        throw new Error("Could not load mission lifecycle.");
      }
      // Server compile is the only graph authority for dispatch. Always recompile so
      // kitchen-sink intake graphs are replaced by composition-selected abilities.
      // Do not pass mission.objective — it is often a lossy restatement; server uses
      // stored composition.instruction when present.
      const storedInstruction = compositionInstructionFromIntake(current.intake ?? null);
      if (!storedInstruction && !current.mission.objective?.trim()) {
        throw new Error("Mission has no composition instruction or objective to compile.");
      }
      const compiled = await compileMission(session, missionId, {
        persist: true,
        source: "mission_dispatch_ui",
      });
      const compileStatus = String(compiled.compile_status ?? "");
      if (compileStatus !== "ready") {
        throw new Error(formatCompileFailure(compiled));
      }
      current = (await refreshLifecycle()) ?? current;
      const compiledActions =
        (compiled.display as { allowed_actions?: string[] } | undefined)?.allowed_actions ??
        intakeAllowedActions(current.intake ?? null);
      if (compiledActions.length === 0) {
        throw new Error("Server compile returned no abilities.");
      }
      // Plan + graph + materialization + admission are server-owned after compile.
      if (!current.completeness.has_runtime_admission) {
        await admitMissionToRuntime(session, missionId, {
          admission_status: "admitted",
          auto_provision_authority: true,
        });
        current = (await refreshLifecycle()) ?? current;
      }

      const readinessResponse = await getMissionRuntimeReadiness(session, missionId);
      setReadiness(readinessResponse);
      if (!readinessResponse.ready) {
        throw new Error("Runtime readiness blocked — review blockers below before materializing tasks.");
      }

      const materialized = await materializeMissionRuntimeTasks(session, missionId);
      setTaskMaterialization(materialized);
      if (materialized.created_execution_task_ids.length > 0) {
        setMonitoredTaskId(materialized.created_execution_task_ids[0]);
      }
      await admitMissionRuntimeQueue(session, missionId);
      await refreshLifecycle();
      await refreshReadinessViews();
      setNotice("Mission is live — tasks materialized and queued for workers.");
    } catch (err) {
      setError(err);
      await refreshLifecycle();
      await refreshReadinessViews();
    } finally {
      setLoading(null);
    }
  }

  // Auto-run remaining ladder when arriving from composition "Start mission" (?execute=1).
  useEffect(() => {
    if (!session || !lifecycle || !missionId) {
      return;
    }
    if (searchParams.get("execute") !== "1") {
      return;
    }
    if (autoExecuteStarted.current || loading !== null) {
      return;
    }
    if (allowedActions.length === 0) {
      return;
    }
    autoExecuteStarted.current = true;
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("execute");
        return next;
      },
      { replace: true },
    );
    void handleRunPipeline();
    // Intentionally once per mission load with execute=1.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- auto-start handoff
  }, [session, lifecycle, missionId, searchParams, allowedActions.length, loading]);

  if (!missionId) {
    return (
      <main className="page-shell narrow">
        <p className="muted">Missing mission id.</p>
        <Link to="/missions">Back to missions</Link>
      </main>
    );
  }

  return (
    <main className="page-shell">
      <section className="hero compact-hero">
        <div>
          <p className="eyebrow">Mission execution</p>
          <h1>{lifecycle?.mission.objective ?? "Loading mission…"}</h1>
          <p>
            Ajenda already chose the work for this mission. Start execution to materialize tasks and queue workers —
            without picking skills. Composition missions usually already have a plan and task graph.
          </p>
        </div>
        <div className="hero-actions">
          <Link className="ghost-link" to="/missions">
            All missions
          </Link>
        </div>
      </section>

      {lifecycle ? (
        <section className="panel mission-context-banner">
          <div className="panel-heading-row">
            <h2>Mission context</h2>
            <span className={`status-pill status-${lifecycle.mission.status}`}>{lifecycle.mission.status}</span>
          </div>
          <p className="mission-card-meta">
            <strong>ID:</strong> <code>{lifecycle.mission.mission_id}</code>
          </p>
          {allowedActions.length > 0 ? (
            <p className="mission-card-meta">
              <strong>Ajenda planned {allowedActions.length} step(s)</strong> for this outcome (composition engine —
              not user-selected skills).
            </p>
          ) : (
            <p className="muted">
              This mission has no composed plan yet. Request a mission from the missions page so Ajenda can plan it.
            </p>
          )}
        </section>
      ) : null}

      <section className="panel">
        <div className="panel-heading-row">
          <h2>Execution pipeline</h2>
          <button
            type="button"
            className="primary-button"
            disabled={!session || loading !== null || allowedActions.length === 0}
            onClick={() => void handleRunPipeline()}
          >
            {loading === "Running full pipeline…" ? "Running…" : "Start execution"}
          </button>
        </div>

        <ol className="dispatch-pipeline">
          {PIPELINE_STEPS.map((step) => {
            const status = stepStatusFor(step.id, lifecycle, {
              readiness,
              materialization: taskMaterialization,
              dispatch: dispatchReadiness,
              authorities,
            });
            return (
              <li className={`dispatch-step dispatch-step-${status}`} key={step.id}>
                <div className="dispatch-step-header">
                  <span className="dispatch-step-indicator" aria-hidden />
                  <div>
                    <strong>{step.label}</strong>
                    <span className="dispatch-step-status">{status}</span>
                  </div>
                </div>
                <div className="dispatch-step-actions">
                  {step.id === "plan" ? (
                    <button type="button" className="ghost-button" disabled={!session || loading !== null} onClick={() => void handlePreparePlan()}>
                      {loading === "Creating plan…" ? "Working…" : lifecycle?.completeness.has_plan ? "Recreate plan" : "Create plan"}
                    </button>
                  ) : null}
                  {step.id === "graph" ? (
                    <button type="button" className="ghost-button" disabled={!session || loading !== null || allowedActions.length === 0} onClick={() => void handlePrepareGraph()}>
                      {loading === "Building task graph…" ? "Working…" : lifecycle?.completeness.has_task_graph ? "Replace graph" : "Build graph"}
                    </button>
                  ) : null}
                  {step.id === "materialize" ? (
                    <button type="button" className="ghost-button" disabled={!session || loading !== null || allowedActions.length === 0} onClick={() => void handleMaterializeGraph()}>
                      {loading === "Materializing graph…" ? "Working…" : "Materialize"}
                    </button>
                  ) : null}
                  {step.id === "authority" ? (
                    <button type="button" className="ghost-button" disabled={!session || loading !== null} onClick={() => void handleProvisionAuthority()}>
                      {loading === "Provisioning runtime authority…" ? "Working…" : "Provision authority"}
                    </button>
                  ) : null}
                  {step.id === "admit" ? (
                    <button type="button" className="ghost-button" disabled={!session || loading !== null || allowedActions.length === 0} onClick={() => void handleAdmitRuntime()}>
                      {loading === "Admitting to runtime…" ? "Working…" : "Admit to runtime"}
                    </button>
                  ) : null}
                  {step.id === "readiness" ? (
                    <button type="button" className="ghost-button" disabled={!session || loading !== null} onClick={() => void handleCheckReadiness()}>
                      {loading === "Checking readiness…" ? "Working…" : "Check readiness"}
                    </button>
                  ) : null}
                  {step.id === "tasks" ? (
                    <button type="button" className="ghost-button" disabled={!session || loading !== null} onClick={() => void handleMaterializeTasks()}>
                      {loading === "Materializing runtime tasks…" ? "Working…" : "Materialize tasks"}
                    </button>
                  ) : null}
                  {step.id === "queue" ? (
                    <button type="button" className="ghost-button" disabled={!session || loading !== null} onClick={() => void handleQueueAdmission()}>
                      {loading === "Queueing tasks…" ? "Working…" : "Queue for workers"}
                    </button>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
      </section>

      {lifecycle && lifecycle.missing_next_steps.length > 0 ? (
        <section className="panel">
          <h2>Runtime gaps</h2>
          <p className="muted">These block worker execution until resolved.</p>
          <ul className="violation-list">
            {lifecycle.missing_next_steps.map((item) => (
              <li key={item}>
                <code>{item}</code>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {lifecycle && (lifecycle.optional_closeout_steps?.length ?? 0) > 0 ? (
        <section className="panel">
          <h2>Optional mission close-out</h2>
          <p className="muted">
            Execution can already be complete. These are product follow-ups (review, memory, retrieval) — not
            pipeline failures.
          </p>
          <ul className="violation-list">
            {(lifecycle.optional_closeout_steps ?? []).map((item) => (
              <li key={item}>
                <code>{item}</code>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {readiness && (readiness.blockers.length > 0 || readiness.warnings.length > 0) ? (
        <section className="panel">
          <h2>Runtime readiness</h2>
          <p className="muted">
            Status: <strong>{readiness.readiness_status}</strong> · Ready: <strong>{readiness.ready ? "yes" : "no"}</strong>
          </p>
          {readiness.blockers.length > 0 ? (
            <ul className="violation-list">
              {readiness.blockers.map((item) => (
                <li key={item.code}>
                  <strong>{item.code}</strong>
                  <span>{item.message}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}

      {taskMaterialization && taskMaterialization.created_execution_task_ids.length > 0 ? (
        <section className="panel">
          <h2>Materialized tasks</h2>
          <ul className="task-id-list">
            {taskMaterialization.created_execution_task_ids.map((taskId) => (
              <li key={taskId}>
                <button type="button" className="ghost-button task-id-button" onClick={() => setMonitoredTaskId(taskId)}>
                  <code>{taskId}</code>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {monitoredTaskId && taskStatus ? (
        <section className="panel">
          <h2>Task monitor</h2>
          <p className="mission-card-meta">
            <code>{monitoredTaskId}</code> · <strong>{taskStatus.status}</strong>
            {taskStatus.action ? ` · ${taskStatus.action}` : ""}
          </p>
          <pre className="code-block">{pretty(taskStatus)}</pre>
        </section>
      ) : null}

      {notice ? (
        <section className="panel success-panel">
          <p>{notice}</p>
        </section>
      ) : null}

      <PageErrorAlert error={error} />
    </main>
  );
}