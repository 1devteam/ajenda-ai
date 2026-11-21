import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import {
  admitMissionRuntimeQueue,
  admitMissionToRuntime,
  compileMission,
  createMissionPlan,
  getMissionDispatchReadiness,
  getMissionDeliverable,
  getProfileDeliverable,
  getMissionLifecycle,
  getMissionRuntimeEvidence,
  getMissionRuntimeReadiness,
  getMissionRuntimeTaskMaterialization,
  getTaskStatus,
  launchMission,
  materializeMissionRuntimeTasks,
  provisionBridgeRuntimeAuthority,
} from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import PageErrorAlert from "../components/PageErrorAlert";
import { EmailReferences } from "../components/EmailReferences";
import type {
  AbilityTaskStatusResponse,
  ApiFailure,
  MissionLaunchResponse,
  BridgeRuntimeAuthorityReadResponse,
  MissionLifecycleReadResponse,
  RuntimeDispatchReadinessReadResponse,
  RuntimeReadinessReadResponse,
  RuntimeTaskMaterializationReadResponse,
  MissionDeliverableResponse,
  ProfileDeliverableResponse,
  MissionRuntimeEvidenceProjection,
} from "../types";
import {
  buildMissionPlanPayload,
  intakeAllowedActions,
  intakeSuccessCriteria,
  PIPELINE_STEPS,
} from "../utils/missionBridge";
import { failureText, pretty } from "../utils/errors";

import { GoalEvaluationResult, PublicResearchResult, resultRecord, resultRows } from "./MissionResultDetails";

import "./missionDispatch.css";

type StepStatus = "pending" | "complete" | "blocked" | "partially admitted";

const CLOSED_MISSION_STATES = new Set(["completed", "failed", "cancelled", "archived"]);

function queueStepStatus(
  materialization: RuntimeTaskMaterializationReadResponse | null,
  dispatch: RuntimeDispatchReadinessReadResponse | null,
): StepStatus {
  const receipt = dispatch?.queue_admission_reference;
  if (!receipt) return "pending";
  if (
    materialization?.materialization_status !== "materialized" ||
    receipt.mission_id !== materialization.mission_id ||
    receipt.tenant_id !== materialization.tenant_id ||
    !Array.isArray(receipt.materialized_execution_task_ids) ||
    !Array.isArray(receipt.admitted_execution_task_ids)
  ) {
    return "blocked";
  }

  const current = new Set(materialization.created_execution_task_ids);
  const covered = new Set(receipt.materialized_execution_task_ids);
  const admitted = new Set(receipt.admitted_execution_task_ids);
  if (
    current.size === 0 ||
    covered.size !== current.size ||
    [...current].some((id) => !covered.has(id)) ||
    [...admitted].some((id) => !current.has(id))
  ) {
    return "blocked";
  }

  if (receipt.admission_status === "admitted" && admitted.size === current.size) return "complete";
  if (receipt.admission_status === "partially_admitted" && admitted.size > 0) return "partially admitted";
  return "blocked";
}

function crmOutcomeFromTask(task: AbilityTaskStatusResponse | null): {
  persisted: number;
  verified: number;
  opportunities: string[];
} | null {
  if (!task || task.action !== "record.write") {
    return null;
  }
  const metadata = task.metadata_json ?? {};
  const handler = metadata.handler_result;
  const envelope = handler && typeof handler === "object" ? (handler as Record<string, unknown>) : metadata;
  const output = envelope.output;
  if (!output || typeof output !== "object") {
    return null;
  }
  const payload = output as Record<string, unknown>;
  const projections = Array.isArray(payload.crm_projection_records) ? payload.crm_projection_records : [];
  const persisted = typeof payload.persisted_count === "number" ? payload.persisted_count : 0;
  const verified = typeof payload.readback_verified_count === "number" ? payload.readback_verified_count : 0;
  const opportunities = projections
    .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"))
    .map((item) => (typeof item.opportunity_id === "string" ? item.opportunity_id : ""))
    .filter(Boolean);
  return { persisted, verified, opportunities };
}

function compositionReadyFromIntake(intake: Record<string, unknown> | null | undefined): boolean {
  if (!intake || typeof intake !== "object") {
    return true;
  }
  const context = intake.context;
  if (!context || typeof context !== "object") {
    return true;
  }
  const composition = (context as { composition?: unknown }).composition;
  if (!composition || typeof composition !== "object") {
    return true;
  }
  const record = composition as Record<string, unknown>;
  if (record.ready_to_start === false || record.proposal_status === "gaps_open") {
    return false;
  }
  return true;
}

function deliverableFromTaskStatus(task: AbilityTaskStatusResponse): MissionDeliverableResponse | null {
  const metadata = task.metadata_json ?? {};
  const handler = metadata.handler_result;
  const envelope = handler && typeof handler === "object" ? (handler as Record<string, unknown>) : metadata;
  const output = envelope.output;
  if (!output || typeof output !== "object") {
    return null;
  }
  const payload = output as Record<string, unknown>;
  const browserObservation = payload.web_page_observation;
  if (browserObservation && typeof browserObservation === "object") {
    return {
      schema_version: 1,
      kind: "task_output_fallback",
      mission_id: task.mission_id ?? "",
      objective: task.description ?? "",
      artifacts: { web_page_observation: browserObservation },
      prospects: [],
      limitations: ["Rendered from persisted task output because the assembled deliverable read model is unavailable."],
      task_state: {
        task_count: 1,
        statuses: { [task.status]: 1 },
        all_terminal: ["completed", "failed", "blocked", "cancelled"].includes(task.status),
        all_succeeded: task.status === "completed",
      },
      completion: {
        artifact_complete: task.status === "completed",
        complete: task.status === "completed",
        missing_fields: [],
        invalid_fields: [],
        assembly_errors: [],
      },
    };
  }
  const identityObservation = payload.public_identity_observation;
  if (identityObservation && typeof identityObservation === "object") {
    return {
      schema_version: 1,
      kind: "task_output_fallback",
      mission_id: task.mission_id ?? "",
      objective: task.description ?? "",
      artifacts: { public_identity_observation: identityObservation },
      prospects: [],
      limitations: ["Rendered from persisted task output because the assembled deliverable read model is unavailable."],
      task_state: {
        task_count: 1,
        statuses: { [task.status]: 1 },
        all_terminal: ["completed", "failed", "blocked", "cancelled"].includes(task.status),
        all_succeeded: task.status === "completed",
      },
      completion: {
        artifact_complete: task.status === "completed",
        complete: task.status === "completed",
        missing_fields: [],
        invalid_fields: [],
        assembly_errors: [],
      },
    };
  }
  const rawRows = payload.prospect_candidates;
  if (!Array.isArray(rawRows)) {
    return null;
  }
  const prospects = rawRows.filter((row): row is Record<string, unknown> => Boolean(row && typeof row === "object")).map((row) => ({
    prospect_id: typeof row.prospect_id === "string" ? row.prospect_id : null,
    company_name: typeof row.company === "string" ? row.company : null,
    website: typeof row.website === "string" ? row.website : null,
    product_description: typeof row.product_description === "string" ? row.product_description : null,
    research_summary: typeof row.research_summary === "string" ? row.research_summary : null,
    sources: Array.isArray(row.sources) ? row.sources.filter((source): source is string => typeof source === "string") : [],
  }));
  return {
    schema_version: 1,
    kind: "task_output_fallback",
    mission_id: task.mission_id ?? "",
    objective: task.description ?? "",
    prospects,
    limitations: ["Rendered from persisted task output because the assembled deliverable read model is unavailable."],
    task_state: {
      task_count: 1,
      statuses: { [task.status]: 1 },
      all_terminal: ["completed", "failed", "blocked", "cancelled"].includes(task.status),
      all_succeeded: task.status === "completed",
    },
    completion: {
      artifact_complete: prospects.length > 0,
      complete: prospects.length > 0 && task.status === "completed",
      missing_fields: [],
      invalid_fields: [],
      assembly_errors: [],
    },
  };
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

function launchRequestError(error: unknown): unknown {
  const body = (error as Partial<ApiFailure> | null)?.body;
  if (typeof body === "object" && body !== null && "detail" in body) {
    const detail = body.detail;
    if (
      typeof detail === "object" && detail !== null &&
      "code" in detail && detail.code === "COMPILE_NOT_READY" &&
      "compile" in detail && typeof detail.compile === "object" && detail.compile !== null
    ) {
      return `Mission launch stopped at graph compilation. ${formatCompileFailure(detail.compile as Record<string, unknown>)}`;
    }
  }
  return error;
}

function queueAdmissionFailure(response: MissionLaunchResponse): string {
  const summary = [
    "Queue admission reported blockers.",
    `${response.queued_task_ids.length} task(s) queued in this launch.`,
  ];
  if (response.pending_review_task_ids.length > 0) {
    summary.push(`${response.pending_review_task_ids.length} task(s) waiting for policy review.`);
  }
  const blockers = response.blockers.map(({ code, message, reason, task_id }) => {
    const detail = [
      typeof message === "string" ? message : "",
      typeof reason === "string" && reason !== message ? reason : "",
      typeof task_id === "string" ? `Task ${task_id}` : "",
    ].filter(Boolean).join(" ");
    return [typeof code === "string" ? code : "", detail].filter(Boolean).join(" — ") || "Unspecified queue blocker";
  });
  return [summary.join(" "), ...blockers].join("\n");
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
      // Full-pipeline execution provisions bridge authority as part of server-owned
      // runtime admission; do not require a manual UI provision response to turn green.
      return extras.authorities || completeness.has_runtime_admission ? "complete" : "pending";
    case "admit":
      return completeness.has_runtime_admission ? "complete" : "pending";
    case "readiness":
      return extras.readiness?.ready ? "complete" : extras.readiness ? "blocked" : "pending";
    case "tasks":
      return extras.materialization?.materialization_status === "materialized" ? "complete"
        : extras.materialization?.materialization_status === "blocked" ? "blocked" : "pending";
    case "queue":
      return queueStepStatus(extras.materialization, extras.dispatch);
    default:
      return "pending";
  }
}

export default function MissionDispatchPage() {
  const { missionId = "" } = useParams();
  return <MissionDispatch key={missionId} missionId={missionId} />;
}

function MissionDispatch({ missionId }: { missionId: string }) {
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
  const [launchError, setLaunchError] = useState<unknown>(null);
  const [notice, setNotice] = useState("");
  const [monitoredTaskId, setMonitoredTaskId] = useState("");
  const [taskStatus, setTaskStatus] = useState<AbilityTaskStatusResponse | null>(null);
  const [deliverable, setDeliverable] = useState<MissionDeliverableResponse | null>(null);
  const [profileDeliverable, setProfileDeliverable] = useState<ProfileDeliverableResponse | null>(null);
  const [runtimeEvidence, setRuntimeEvidence] = useState<MissionRuntimeEvidenceProjection | null>(null);

  const allowedActions = useMemo(() => intakeAllowedActions(lifecycle?.intake ?? null), [lifecycle?.intake]);
  const internalSearchOnly = allowedActions.length === 1 && allowedActions[0] === "record.search";
  const closed = Boolean(lifecycle && CLOSED_MISSION_STATES.has(lifecycle.mission.status));
  const directTaskExecution = lifecycle?.completeness.has_task_graph === false
    && lifecycle.completeness.has_materialization === false
    && lifecycle.completeness.has_runtime_admission === false
    && Boolean(runtimeEvidence?.task_flows.length)
    && runtimeEvidence?.task_flows.every((task) => typeof task.task_id === "string" && task.node_key === null)
    && runtimeEvidence?.task_flows.some((task) => task.queue_admitted === true);
  const acceptance = runtimeEvidence?.acceptance?.status
    ? runtimeEvidence.acceptance : deliverable?.result_semantics?.mission_acceptance;
  const acceptanceRecord = acceptance && typeof acceptance === "object"
    ? acceptance as Record<string, unknown> : null;
  const acceptanceEvaluationError = acceptanceRecord?.status === "evaluation_error";
  const acceptanceIncomplete = acceptanceEvaluationError
    || acceptanceRecord?.status === "partially_met" || acceptanceRecord?.status === "failed";
  const acceptanceReasons = Array.isArray(acceptanceRecord?.reasons)
    ? [...new Set(acceptanceRecord.reasons.filter(
      (reason): reason is string => typeof reason === "string" && reason.trim().length > 0,
    ))]
    : [];
  const pipeline = PIPELINE_STEPS.map((step) => ({
    ...step,
    status: stepStatusFor(step.id, lifecycle, {
      readiness,
      materialization: taskMaterialization,
      dispatch: dispatchReadiness,
      authorities,
    }),
  }));
  const nextStage = pipeline.find((step) => step.status !== "complete");
  let launchUnavailable = "";
  if (!session) {
    launchUnavailable = "Sign in to start execution.";
  } else if (!lifecycle || lifecycle.mission.mission_id !== missionId) {
    launchUnavailable = "Mission details must load before execution can start.";
  } else if (closed || directTaskExecution) {
    launchUnavailable = "This mission is available for review.";
  } else if (!compositionReadyFromIntake(lifecycle.intake)) {
    launchUnavailable = "Ajenda needs clarification on the mission before execution can start. Review the mission request in Missions.";
  } else if (allowedActions.length === 0) {
    launchUnavailable = "No executable steps were planned for this mission.";
  }
  const successCriteria = useMemo(() => intakeSuccessCriteria(lifecycle?.intake ?? null), [lifecycle?.intake]);
  const crmOutcome = useMemo(() => crmOutcomeFromTask(taskStatus), [taskStatus]);

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
    const [readinessResult, dispatchResult, materializationResult] = await Promise.allSettled([
      getMissionRuntimeReadiness(session, missionId),
      getMissionDispatchReadiness(session, missionId),
      getMissionRuntimeTaskMaterialization(session, missionId),
    ]);
    setReadiness(readinessResult.status === "fulfilled" ? readinessResult.value : null);
    setDispatchReadiness(dispatchResult.status === "fulfilled" ? dispatchResult.value : null);
    setTaskMaterialization(materializationResult.status === "fulfilled" ? materializationResult.value : null);
    for (const result of [readinessResult, dispatchResult, materializationResult]) {
      if (result.status === "rejected" && result.reason?.status !== 404) setError(result.reason);
    }
  }, [session, missionId]);

  const refreshDeliverable = useCallback(async (taskOverride?: AbilityTaskStatusResponse | null) => {
    if (!session || !missionId) {
      return;
    }
    try {
      const result = await getMissionDeliverable(session, missionId);
      setProfileDeliverable(null);
      setDeliverable(result);
    } catch (err) {
      const status = typeof err === "object" && err && "status" in err ? Number((err as { status?: unknown }).status) : 0;
      if (status === 404) {
        try {
          const profile = await getProfileDeliverable(session, missionId);
          setDeliverable(null);
          setProfileDeliverable(profile);
          return;
        } catch (profileError) {
          const profileStatus = typeof profileError === "object" && profileError && "status" in profileError
            ? Number((profileError as { status?: unknown }).status) : 0;
          if (profileStatus !== 404) {
            setError(profileError);
            return;
          }
        }
      }
      const fallback = taskOverride ? deliverableFromTaskStatus(taskOverride) : null;
      if (status === 404 && fallback) {
        setProfileDeliverable(null);
        setDeliverable(fallback);
      } else if (status === 404) {
        setProfileDeliverable(null);
        setDeliverable(null);
      } else if (status !== 404) {
        setError(err);
      }
    }
  }, [session, missionId]);

  const refreshRuntimeEvidence = useCallback(async () => {
    if (!session || !missionId) {
      return;
    }
    try {
      setRuntimeEvidence(await getMissionRuntimeEvidence(session, missionId));
    } catch {
      // Runtime evidence is a read-only diagnostic surface. A principal
      // without runtime-view permission must not make the mission appear
      // failed or change the deliverable state.
      setRuntimeEvidence(null);
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
        await Promise.all([refreshReadinessViews(), refreshDeliverable(), refreshRuntimeEvidence()]);
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
  }, [session, missionId, refreshReadinessViews, refreshDeliverable, refreshRuntimeEvidence]);

  useEffect(() => {
    if (!session || !monitoredTaskId) {
      return;
    }
    let cancelled = false;
    let timer: number | undefined;
    async function poll() {
      try {
        const status = await getTaskStatus(session!, monitoredTaskId);
        if (cancelled) return;
        setTaskStatus(status);
        await Promise.all([
          refreshDeliverable(status),
          refreshRuntimeEvidence(),
          ...(!closed ? [refreshLifecycle(), refreshReadinessViews()] : []),
        ]);
      } catch (err) {
        if (!cancelled) {
          setError(err);
        }
      }
      if (!cancelled && !closed) {
        timer = window.setTimeout(() => void poll(), 3000);
      }
    }
    void poll();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [session, monitoredTaskId, closed, refreshDeliverable, refreshLifecycle, refreshReadinessViews, refreshRuntimeEvidence]);

  async function runStep(label: string, fn: () => Promise<void>) {
    if (closed || directTaskExecution || lifecycle?.mission.mission_id !== missionId) return;
    setLoading(label);
    setLaunchError(null);
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
    if (!session || launchUnavailable || loading !== null) {
      return;
    }
    setLoading("Running full pipeline…");
    setError(null);
    setLaunchError(null);
    setNotice("");
    try {
      const response = await launchMission(session, missionId);
      if (response.queued_task_ids.length > 0) {
        setMonitoredTaskId(response.queued_task_ids[0]);
      }
      if (response.blockers.length > 0) {
        setLaunchError(queueAdmissionFailure(response));
      } else {
        setNotice(`Mission launch finished. ${response.queued_task_ids.length} task(s) queued in this launch.`);
      }
    } catch (err) {
      setLaunchError(launchRequestError(err));
    } finally {
      await Promise.all([
        refreshLifecycle().catch(setError),
        refreshReadinessViews(),
        refreshRuntimeEvidence(),
      ]);
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
  }, [session, lifecycle, missionId, searchParams, launchUnavailable, loading]);

  if (!missionId) {
    return (
      <main className="page-shell narrow">
        <p className="muted">Missing mission id.</p>
        <Link to="/missions">Back to missions</Link>
      </main>
    );
  }

  return (
    <main className="page-shell mission-dispatch">
      <section className="hero compact-hero">
        <div>
          <p className="eyebrow">Mission execution</p>
          <h1>{lifecycle?.mission.objective ?? "Loading mission…"}</h1>
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
          {directTaskExecution ? null : allowedActions.length > 0 ? (
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
          <h2>{directTaskExecution ? "Direct task execution" : "Execution pipeline"}</h2>
          {closed ? <Link className="ghost-link" to="/missions">Plan a new run</Link> : directTaskExecution ? null : <button
            type="button"
            className="primary-button"
            disabled={Boolean(launchUnavailable) || loading !== null}
            aria-describedby={launchUnavailable ? "mission-launch-unavailable" : undefined}
            onClick={() => void handleRunPipeline()}
          >
            {loading === "Running full pipeline…" ? "Running…" : "Start execution"}
          </button>}
        </div>

        {directTaskExecution ? (
          <p>Recorded tasks ran through the direct execution path.</p>
        ) : null}
        {!closed && !directTaskExecution && launchUnavailable ? (
          <p id="mission-launch-unavailable" className="muted">{launchUnavailable}</p>
        ) : null}
        <PageErrorAlert error={launchError} />

        {notice ? <p role="status">{notice}</p> : null}
        {lifecycle && nextStage && !closed && !directTaskExecution ? (
          <p className="mission-card-meta">Next incomplete stage: <strong>{nextStage.label}</strong></p>
        ) : null}
        {!closed && !directTaskExecution && readiness?.blockers[0] ? <p className="mission-card-meta">{readiness.blockers[0].message}</p> : null}

        {!directTaskExecution ? <details className="dispatch-diagnostics">
          <summary>{closed ? "Recorded pipeline stages" : "Pipeline diagnostics and controls"}</summary>
          <ol className="dispatch-pipeline">
            {pipeline.map((step) => (
              <li className={`dispatch-step dispatch-step-${step.status.replace(" ", "-")}`} key={step.id}>
                <div className="dispatch-step-header">
                  <span className="dispatch-step-indicator" aria-hidden />
                  <div>
                    <strong>{step.label}</strong>
                    <span className="dispatch-step-status">{closed && step.status === "pending" ? "not recorded" : step.status}</span>
                  </div>
                </div>
                {!closed ? <div className="dispatch-step-actions">
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
                </div> : null}
              </li>
            ))}
          </ol>
        </details> : null}
      </section>

      {lifecycle && !closed && !directTaskExecution && lifecycle.missing_next_steps.length > 0 ? (
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

      {!closed && !directTaskExecution && readiness && (readiness.blockers.length > 0 || readiness.warnings.length > 0) ? (
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

      {profileDeliverable ? (
        <section className="panel" aria-label="Business profile deliverable">
          <h2>Approved business profile</h2>
          <p>{profileDeliverable.complete ? "Profile artifact available" : "Profile artifact incomplete"}</p>
          {profileDeliverable.company_introduction_draft ? (() => {
            const facts = resultRecord(profileDeliverable.profile_brief.facts);
            const headings = [
              ["business_name", "Company"],
              ["description", "Overview"],
              ["products_services", "Products and services"],
              ["target_customers", "Who it serves"],
              ["differentiators", "Differentiators"],
            ];
            return <section aria-label="Company brief">
              <h3>Company brief</h3>
              <dl>
                {headings.flatMap(([field, title]) => {
                  const value = facts?.[field];
                  const content = Array.isArray(value)
                    ? value.filter((item): item is string => typeof item === "string").join(", ")
                    : typeof value === "string" ? value : "";
                  return content ? [<div key={field}><dt>{title}</dt><dd>{content}</dd></div>] : [];
                })}
              </dl>
            </section>;
          })() : null}
          {profileDeliverable.company_introduction_draft ? (
            <section aria-label="Company introduction draft">
              <h3>Company introduction draft</h3>
              <p>For review. Based on approved profile facts.</p>
              {profileDeliverable.company_introduction_draft.body.split("\n\n").map((section, index) => (
                <p key={index}>{section}</p>
              ))}
              {profileDeliverable.company_introduction_draft.memory_reference_ids.length ? (
                <p>Internal memory references found: {profileDeliverable.company_introduction_draft.memory_reference_ids.join(", ")}</p>
              ) : profileDeliverable.company_introduction_draft.memory_lookup_status === "unavailable" ? (
                <p>Internal memory search was unavailable.</p>
              ) : profileDeliverable.company_introduction_draft.memory_lookup_status === "no_matches" ? (
                <p>Internal memory search returned no matching references.</p>
              ) : <p>No internal memory references were recorded.</p>}
              <details>
                <summary>Approved profile evidence</summary>
                <pre className="code-block">{pretty(profileDeliverable.profile_brief)}</pre>
              </details>
            </section>
          ) : <pre className="code-block">{pretty(profileDeliverable.profile_brief)}</pre>}
          <p>Missing fields: {profileDeliverable.missing_fields.length ? profileDeliverable.missing_fields.join(", ") : "none recorded"}</p>
          <p>Conflicting fields: {profileDeliverable.conflicting_fields.length ? profileDeliverable.conflicting_fields.join(", ") : "none recorded"}</p>
          <p>Source: approved business profile ({profileDeliverable.profile_id ?? "profile ID not recorded"})</p>
          <p>Profile source evidence: {profileDeliverable.profile_source_evidence_ids?.length ? profileDeliverable.profile_source_evidence_ids.join(", ") : "not recorded"}</p>
        </section>
      ) : null}

      {closed && acceptanceIncomplete ? (
        <section className="panel" aria-label="Outcome acceptance">
          <h2>Outcome acceptance</h2>
          <p>{acceptanceEvaluationError
            ? "Ajenda could not evaluate the deliverable."
            : acceptanceRecord?.status === "partially_met" ? "Requirements partially met." : "Requirements unmet."}</p>
          {acceptanceReasons.length > 0 ? (
            <ul>{acceptanceReasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
          ) : null}
        </section>
      ) : null}

      {deliverable ? (
        <section className="panel" aria-label="Mission deliverable">
          {(() => {
            const goalEvaluation = resultRecord(deliverable.artifacts?.goal_progress_evaluation);
            const researchReport = resultRecord(deliverable.artifacts?.research_report);
            const researchStages = resultRows(deliverable.result_semantics?.public_research_stages);
            const showResearch = researchReport !== null || researchStages.length > 0;
            const observation = deliverable.artifacts?.web_page_observation;
            const isWebObservation = Boolean(observation && typeof observation === "object");
            const identity = deliverable.artifacts?.public_identity_observation;
            const isIdentityObservation = Boolean(identity && typeof identity === "object");
            const emailReferences = Array.isArray(deliverable.artifacts?.email_messages)
              ? deliverable.artifacts.email_messages
              : null;
            const calendarEvents = Array.isArray(deliverable.artifacts?.calendar_events)
              ? deliverable.artifacts.calendar_events
              : null;
            const rawCrmRecords = deliverable.artifacts?.crm_records;
            const crmRecords = Array.isArray(rawCrmRecords) ? rawCrmRecords : null;
            const crmNames = crmRecords?.flatMap((record: unknown) => {
              if (typeof record !== "object" || record === null) return [];
              const { name, company } = record as { name?: unknown; company?: unknown };
              const label = typeof name === "string" && name.trim() ? name : company;
              return typeof label === "string" && label.trim() ? [label] : [];
            }) ?? [];
            const showInternalSearch = internalSearchOnly || (allowedActions.includes("record.search") && crmRecords !== null);
            const observationRecord = isWebObservation
              ? (observation as Record<string, unknown>)
              : null;
            const identityRecord = isIdentityObservation ? (identity as Record<string, unknown>) : null;
            return (
              <>
          <div className="panel-heading-row">
            <div>
              <p className="cc-section-kicker">Durable output</p>
              <h2>
                {goalEvaluation ? "Goal evaluation" : showResearch ? "Public research" : emailReferences ? "Gmail message references" : calendarEvents ? "Calendar events" : isWebObservation ? "Web page observation" : isIdentityObservation ? "Public identity observation" : showInternalSearch ? "Internal CRM search" : "Prospect candidates"}
              </h2>
            </div>
            <span
              className={`status-pill status-${
                deliverable.completion.artifact_complete ? "completed" : "blocked"
              }`}
            >
              {deliverable.completion.artifact_complete ? "artifact complete" : "incomplete"}
            </span>
          </div>
          {!emailReferences && deliverable.task_state.all_succeeded && !deliverable.completion.artifact_complete ? (
            <p className="callout">
              Tasks succeeded, but the requested artifact is incomplete. Ajenda is not treating this mission as
              successful.
            </p>
          ) : null}
          {goalEvaluation ? <GoalEvaluationResult evaluation={goalEvaluation} /> : null}
          {showResearch ? <PublicResearchResult report={researchReport} stages={researchStages} /> : null}
          {emailReferences ? (
            <EmailReferences messages={emailReferences} sourceObservations={deliverable.result_semantics?.source_observations} />
          ) : calendarEvents ? (
            <div aria-label="Calendar events">
              <h3>Calendar events returned</h3>
              {calendarEvents.length ? <pre className="code-block">{pretty(calendarEvents)}</pre> : <p>No events returned in the recorded provider page.</p>}
            </div>
          ) : observationRecord ? (
            <div className="code-block">
              <p><strong>Source URL:</strong> {String(observationRecord.source_url ?? "—")}</p>
              <p><strong>Final URL:</strong> {String(observationRecord.final_url ?? "—")}</p>
              <p><strong>Title:</strong> {String(observationRecord.title ?? "—")}</p>
              <p><strong>Observed at:</strong> {String(observationRecord.observation_timestamp ?? "—")}</p>
              <p><strong>Observation satisfied:</strong> {observationRecord.observation_satisfied === true ? "yes" : "no"}</p>
              <h3>Extracted observations</h3>
              <pre>{pretty(observationRecord.extracted_observations ?? [])}</pre>
              <h3>Browser step trace</h3>
              <pre>{pretty(observationRecord.browser_trace ?? [])}</pre>
              <h3>Blocked requests</h3>
              <pre>{pretty(observationRecord.blocked_requests ?? [])}</pre>
            </div>
          ) : identityRecord ? (
            <div className="code-block">
              <p><strong>Source URL:</strong> {String(identityRecord.source_url ?? "—")}</p>
              <p><strong>Final URL:</strong> {String(identityRecord.final_url ?? "—")}</p>
              <p><strong>Title:</strong> {String(identityRecord.title ?? "—")}</p>
              <p><strong>Expected company:</strong> {String(identityRecord.expected_company ?? "—")}</p>
              <p><strong>Identity status:</strong> {String(identityRecord.identity_status ?? "—")}</p>
              <p><strong>Evidence URLs:</strong> {pretty(identityRecord.identity_evidence_urls ?? [])}</p>
              <p><strong>Match reasons:</strong> {pretty(identityRecord.identity_match_reasons ?? [])}</p>
              <p><strong>Match evidence:</strong></p>
              <pre>{pretty(identityRecord.identity_match_evidence ?? [])}</pre>
              <p><strong>Identity gaps:</strong> {pretty(identityRecord.identity_gaps ?? [])}</p>
            </div>
          ) : showInternalSearch ? (
            <div aria-label="Internal CRM search results">
              {crmNames.length > 0 ? (
                <ul>{crmNames.map((name, index) => <li key={`${name}-${index}`}>{name}</li>)}</ul>
              ) : crmRecords?.length === 0 && deliverable.completion.complete && deliverable.task_state.all_succeeded ? (
                <p>No matching internal CRM records.</p>
              ) : (
                <p className="muted">No verified internal CRM search result is available yet.</p>
              )}
            </div>
          ) : deliverable.prospects.length > 0 ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Company</th>
                    <th>Website</th>
                    <th>Summary</th>
                    <th>Sources</th>
                  </tr>
                </thead>
                <tbody>
                  {deliverable.prospects.map((prospect, index) => (
                    <tr key={prospect.prospect_id ?? `${prospect.company_name ?? "prospect"}-${index}`}>
                      <td>{prospect.company_name ?? "Unresolved company"}</td>
                      <td>
                        {prospect.website ? (
                          <a href={prospect.website} target="_blank" rel="noreferrer">
                            {prospect.website}
                          </a>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td>{prospect.research_summary ?? prospect.product_description ?? "—"}</td>
                      <td>{prospect.sources.length > 0 ? prospect.sources.join(", ") : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : goalEvaluation || showResearch ? null : (
            <p className="muted">No prospect candidates were produced.</p>
          )}
          {deliverable.limitations?.length ? (
            <div aria-label="Deliverable limitations">
              <h3>Evidence limits</h3>
              <ul>{deliverable.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
          ) : null}
          {deliverable.completion.assembly_errors.length > 0 ? (
            <ul className="violation-list">
              {deliverable.completion.assembly_errors.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : null}
              </>
            );
          })()}
        </section>
      ) : null}

      {runtimeEvidence ? (
        <section className="panel" aria-label="Mission runtime evidence">
          <div className="panel-heading-row">
            <div>
              <p className="cc-section-kicker">Read-only GRAFT runtime evidence</p>
              <h2>Observed execution flow</h2>
            </div>
            <span className="status-pill status-completed">no authority</span>
          </div>
          <p className="mission-card-meta">
            First divergence: <strong>{runtimeEvidence.first_divergence ?? "none recorded"}</strong>
          </p>
          <p className="mission-card-meta">
            {runtimeEvidence.task_flows.length} task flow(s) · {runtimeEvidence.execution_events.length} execution event(s) ·{" "}
            {runtimeEvidence.record_flows.length} artifact record flow(s)
          </p>
          {runtimeEvidence.contradictions.length > 0 ? (
            <>
              <h3>Contradictions</h3>
              <pre className="code-block">{pretty(runtimeEvidence.contradictions)}</pre>
            </>
          ) : null}
          {runtimeEvidence.missing_evidence.length > 0 ? (
            <>
              <h3>Missing evidence</h3>
              <pre className="code-block">{pretty(runtimeEvidence.missing_evidence)}</pre>
            </>
          ) : null}
          <details>
            <summary>Show observed task flows and execution events</summary>
            <pre className="code-block">
              {pretty({ task_flows: runtimeEvidence.task_flows, execution_events: runtimeEvidence.execution_events })}
            </pre>
          </details>
        </section>
      ) : null}

      {allowedActions.includes("record.write") ? (
        <section className="panel success-panel" aria-label="CRM outcome">
          <h2>Internal CRM outcome</h2>
          {crmOutcome ? (
            <p className="mission-card-meta">
              Persisted <strong>{crmOutcome.persisted}</strong> record(s) · Read-back verified{" "}
              <strong>{crmOutcome.verified}</strong> · Linked opportunities: <strong>{crmOutcome.opportunities.length}</strong>
            </p>
          ) : (
            <p className="mission-card-meta">
              Select the <code>record.write</code> task in Materialized tasks to load persisted CRM counts and linked opportunities.
            </p>
          )}
        </section>
      ) : null}

      <PageErrorAlert error={error} />
    </main>
  );
}
