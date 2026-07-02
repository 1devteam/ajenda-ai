import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  admitMissionRuntimeQueue,
  admitMissionToRuntime,
  createMissionPlan,
  getAccountMe,
  getMissionDispatchReadiness,
  getMissionLifecycle,
  getMissionRuntimeReadiness,
  getTaskStatus,
  materializeMissionGraph,
  materializeMissionRuntimeTasks,
  provisionBridgeRuntimeAuthority,
  upsertMissionTaskGraph,
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
  buildMaterializationPayload,
  buildMissionPlanPayload,
  buildRuntimeAdmissionPayload,
  buildTaskGraphPayload,
  intakeAllowedActions,
  intakeSuccessCriteria,
  PIPELINE_STEPS,
} from "../utils/missionBridge";
import { failureText, pretty } from "../utils/errors";

type StepStatus = "pending" | "complete" | "blocked" | "running";

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
  const { session } = useAuth();

  const [lifecycle, setLifecycle] = useState<MissionLifecycleReadResponse | null>(null);
  const [readiness, setReadiness] = useState<RuntimeReadinessReadResponse | null>(null);
  const [taskMaterialization, setTaskMaterialization] = useState<RuntimeTaskMaterializationReadResponse | null>(null);
  const [dispatchReadiness, setDispatchReadiness] = useState<RuntimeDispatchReadinessReadResponse | null>(null);
  const [authorities, setAuthorities] = useState<BridgeRuntimeAuthorityReadResponse | null>(null);
  const [principalId, setPrincipalId] = useState("mission-dispatch-ui");
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
        const [lifecycleResponse, account] = await Promise.all([
          getMissionLifecycle(session!, missionId),
          getAccountMe(session!),
        ]);
        if (!cancelled) {
          setLifecycle(lifecycleResponse);
          setPrincipalId(account.principal.subject_id || "mission-dispatch-ui");
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
    if (!session || allowedActions.length === 0) {
      setError("This mission has no allowed_actions to build a task graph from.");
      return;
    }
    await runStep("Building task graph…", async () => {
      await upsertMissionTaskGraph(session, missionId, buildTaskGraphPayload(allowedActions));
      setNotice(`Task graph created with ${allowedActions.length} ability node(s).`);
    });
  }

  async function handleMaterializeGraph() {
    if (!session || allowedActions.length === 0) {
      return;
    }
    await runStep("Materializing graph…", async () => {
      await materializeMissionGraph(session, missionId, buildMaterializationPayload(allowedActions));
      setNotice("Graph materialization recorded.");
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
    if (!session || allowedActions.length === 0) {
      return;
    }
    await runStep("Admitting to runtime…", async () => {
      let nodeAuthorities = authorities?.node_authorities ?? [];
      if (nodeAuthorities.length === 0) {
        const provisioned = await provisionBridgeRuntimeAuthority(session, missionId);
        setAuthorities(provisioned);
        nodeAuthorities = provisioned.node_authorities;
      }
      await admitMissionToRuntime(
        session,
        missionId,
        buildRuntimeAdmissionPayload(allowedActions, principalId, nodeAuthorities),
      );
      setNotice("Graph admitted to runtime.");
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
    if (!session || !lifecycle) {
      return;
    }
    setLoading("Running full pipeline…");
    setError(null);
    setNotice("");
    try {
      if (!lifecycle.completeness.has_plan) {
        await createMissionPlan(
          session,
          missionId,
          buildMissionPlanPayload(lifecycle.mission.objective, allowedActions, successCriteria),
        );
      }
      if (allowedActions.length === 0) {
        throw new Error("Mission has no allowed_actions — add abilities when creating the mission.");
      }
      if (!lifecycle.completeness.has_task_graph) {
        await upsertMissionTaskGraph(session, missionId, buildTaskGraphPayload(allowedActions));
      }
      if (!lifecycle.completeness.has_materialization) {
        await materializeMissionGraph(session, missionId, buildMaterializationPayload(allowedActions));
      }
      const provisioned = await provisionBridgeRuntimeAuthority(session, missionId);
      setAuthorities(provisioned);
      if (!lifecycle.completeness.has_runtime_admission) {
        await admitMissionToRuntime(
          session,
          missionId,
          buildRuntimeAdmissionPayload(allowedActions, principalId, provisioned.node_authorities),
        );
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
      setNotice("Pipeline complete — tasks materialized and queued.");
    } catch (err) {
      setError(err);
      await refreshLifecycle();
      await refreshReadinessViews();
    } finally {
      setLoading(null);
    }
  }

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
          <p className="eyebrow">Mission dispatch</p>
          <h1>{lifecycle?.mission.objective ?? "Loading mission…"}</h1>
          <p>
            Prepare the mission graph, admit it to the governed runtime, materialize planned tasks, and queue them for
            worker execution — without bypassing Ajenda&apos;s authority boundaries.
          </p>
        </div>
        <div className="hero-actions">
          <Link className="ghost-link" to="/missions">
            All missions
          </Link>
          <Link className="action-link" to={`/tasks?mission_id=${missionId}`}>
            Launch abilities directly
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
              <strong>Allowed abilities:</strong> {allowedActions.join(", ")}
            </p>
          ) : (
            <p className="muted">No allowed_actions on this mission — dispatch graph cannot be auto-generated.</p>
          )}
        </section>
      ) : null}

      <section className="panel">
        <div className="panel-heading-row">
          <h2>Dispatch pipeline</h2>
          <button
            type="button"
            className="primary-button"
            disabled={!session || loading !== null || allowedActions.length === 0}
            onClick={() => void handleRunPipeline()}
          >
            {loading === "Running full pipeline…" ? "Running…" : "Run full pipeline"}
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
          <h2>Missing next steps</h2>
          <ul className="violation-list">
            {lifecycle.missing_next_steps.map((item) => (
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