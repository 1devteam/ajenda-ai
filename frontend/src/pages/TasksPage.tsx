import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import DisclaimerModal from "../components/DisclaimerModal";
import {
  getAccountMe,
  approveReviewQueueItem,
  getBrainCapabilityCheck,
  getTaskStatus,
  launchProof,
  launchTask,
  listAutonomyDisclaimers,
  listBrainMissions,
  listProviderCredentials,
  listReviewQueue,
} from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import PageErrorAlert from "../components/PageErrorAlert";
import BrainMissionsPanel from "../components/tasks/BrainMissionsPanel";
import ReviewQueuePanel from "../components/tasks/ReviewQueuePanel";
import TaskMonitor from "../components/tasks/TaskMonitor";
import Tier3AutonomyPanel, {
  TIER3_ACTIONS,
  type Tier3Action,
} from "../components/tasks/Tier3AutonomyPanel";
import { mapBrainMissionsFromApi } from "../config/brainMissionCatalog";
import {
  BRAIN_MISSION_TEMPLATES,
  type BrainMissionCapstoneStep,
  type BrainMissionTemplate,
} from "../config/brainMissionTemplates";
import { MISSION_ABILITY_PRESETS, type MissionAbilityPreset } from "../config/missionAbilities";
import type {
  AbilityTaskQueuedResponse,
  AbilityTaskStatusResponse,
  AutonomyDisclaimer,
  BrainCapabilityCheckResponse,
  ProviderCredentialResponse,
  ReviewQueueItem,
} from "../types";
import { newIdempotencyKey } from "../utils/errors";

const PROOF_BUTTONS = [
  { key: "calendar-read" as const, title: "Calendar Read", description: "Read-only calendar proof." },
  { key: "sales-qualify" as const, title: "Sales Qualify", description: "Qualify a sample roofing lead." },
] as const;

export default function TasksPage() {
  const [searchParams] = useSearchParams();
  const missionId = searchParams.get("mission_id")?.trim() ?? "";
  const { session } = useAuth();
  const [activeTaskId, setActiveTaskId] = useState("");
  const [taskStatus, setTaskStatus] = useState<AbilityTaskStatusResponse | null>(null);
  const [lastQueued, setLastQueued] = useState<AbilityTaskQueuedResponse | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [autonomyMode, setAutonomyMode] = useState<"off" | "pilot" | "enforce">("off");
  const [disclaimers, setDisclaimers] = useState<AutonomyDisclaimer[]>([]);
  const [principalId, setPrincipalId] = useState("");
  const [credentials, setCredentials] = useState<ProviderCredentialResponse[]>([]);
  const [tier3Credentials, setTier3Credentials] = useState<Record<Tier3Action, string>>({
    "gtm.email_send": "",
    "gtm.crm_upsert": "",
  });
  const [pendingTier3, setPendingTier3] = useState<Tier3Action | null>(null);
  const [showDisclaimer, setShowDisclaimer] = useState(false);
  const [capabilityReport, setCapabilityReport] = useState<BrainCapabilityCheckResponse | null>(null);
  const [reviewQueue, setReviewQueue] = useState<ReviewQueueItem[]>([]);
  const [activeCapstone, setActiveCapstone] = useState<BrainMissionTemplate | null>(null);
  const [approvedArtifacts, setApprovedArtifacts] = useState<ReviewQueueItem[]>([]);
  const [selectedSendArtifactId, setSelectedSendArtifactId] = useState("");
  const [brainMissionTemplates, setBrainMissionTemplates] =
    useState<BrainMissionTemplate[]>(BRAIN_MISSION_TEMPLATES);

  const draftDisclaimer = disclaimers.find((item) => item.actions.includes("gtm.email_draft")) ?? null;
  const pendingDisclaimer = pendingTier3
    ? disclaimers.find((item) => item.actions.includes(pendingTier3)) ?? null
    : null;

  useEffect(() => {
    if (!session) {
      return;
    }
    let cancelled = false;
    async function loadAutonomyContext() {
      try {
        const [disclaimerResponse, account, credentialResponse] = await Promise.all([
          listAutonomyDisclaimers(session!),
          getAccountMe(session!),
          listProviderCredentials(session!),
        ]);
        if (!cancelled) {
          setAutonomyMode(disclaimerResponse.mode);
          setDisclaimers(disclaimerResponse.disclaimers);
          setPrincipalId(account.principal.subject_id);
          const activeCredentials = credentialResponse.credentials.filter((item) => !item.revoked);
          setCredentials(activeCredentials);
          setTier3Credentials({
            "gtm.email_send":
              activeCredentials.find(
                (item) => item.provider === "external_email" && item.allowed_actions.includes("gtm.email_send"),
              )?.credential_id ?? "",
            "gtm.crm_upsert":
              activeCredentials.find(
                (item) => item.provider === "external_crm" && item.allowed_actions.includes("gtm.crm_upsert"),
              )?.credential_id ?? "",
          });
        }
      } catch (err) {
        if (!cancelled) {
          setAutonomyMode("off");
          setError(err);
        }
      }
    }
    void loadAutonomyContext();
    return () => {
      cancelled = true;
    };
  }, [session]);

  useEffect(() => {
    if (!session) {
      return;
    }
    let cancelled = false;
    async function loadBrainMissions() {
      try {
        const response = await listBrainMissions(session!);
        if (!cancelled && response.missions.length > 0) {
          setBrainMissionTemplates(mapBrainMissionsFromApi(response.missions));
        }
      } catch {
        if (!cancelled) {
          setBrainMissionTemplates(BRAIN_MISSION_TEMPLATES);
        }
      }
    }
    void loadBrainMissions();
    return () => {
      cancelled = true;
    };
  }, [session]);

  useEffect(() => {
    if (!activeTaskId || !session) {
      return;
    }

    let cancelled = false;

    async function poll() {
      if (!session) return;
      try {
        const status = await getTaskStatus(session, activeTaskId);
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
    const timer = window.setInterval(() => {
      void poll();
    }, 2500);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeTaskId, session]);

  function credentialForAction(action: string, provider?: string) {
    return (
      credentials.find(
        (item) =>
          (!provider || item.provider === provider) &&
          item.allowed_actions.includes(action) &&
          !item.revoked,
      ) ?? null
    );
  }

  function credentialForPreset(preset: MissionAbilityPreset) {
    if (!preset.provider) {
      return null;
    }
    return credentialForAction(preset.action, preset.provider);
  }

  function credentialReference(credential: ProviderCredentialResponse) {
    return {
      schema_version: 1 as const,
      credential_id: credential.credential_id,
      provider: credential.provider,
      credential_type: credential.credential_type,
    };
  }

  async function handleMissionAbility(preset: MissionAbilityPreset) {
    if (!session || !missionId) {
      return;
    }
    if (preset.requiresCredential) {
      const credential = credentialForPreset(preset);
      if (!credential) {
        setError(`Connect a credential for ${preset.action} on the Credentials page first.`);
        return;
      }
      setLoading(`Launching ${preset.action}`);
      setError("");
      try {
        const queued = await launchTask(session, {
          action: preset.action,
          input: preset.input,
          mission_id: missionId,
          idempotency_key: newIdempotencyKey(),
          credential_reference: credentialReference(credential),
        });
        setLastQueued(queued);
        setActiveTaskId(queued.task_id);
      } catch (err) {
        setError(err);
      } finally {
        setLoading(null);
      }
      return;
    }

    setLoading(`Launching ${preset.action}`);
    setError("");
    try {
      const queued = await launchTask(session, {
        action: preset.action,
        input: preset.input,
        mission_id: missionId,
        idempotency_key: newIdempotencyKey(),
      });
      setLastQueued(queued);
      setActiveTaskId(queued.task_id);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(null);
    }
  }

  function credentialOptionsFor(action: Tier3Action) {
    const spec = TIER3_ACTIONS.find((item) => item.action === action);
    if (!spec) {
      return [];
    }
    return credentials.filter(
      (item) => item.provider === spec.provider && item.allowed_actions.includes(action),
    );
  }

  async function handleDraftWithDisclaimer() {
    if (!session || !draftDisclaimer || !principalId) {
      return;
    }
    setLoading("Launching email draft");
    setError("");
    try {
      const queued = await launchTask(session, {
        action: "gtm.email_draft",
        mission_id: missionId || undefined,
        input: {
          recipient: "prospect@example.com",
          topic: "Ajenda follow-up",
          tone: "professional",
          context: { source: "tasks-ui", goal: "Product runtime disclaimer path" },
        },
        autonomy_acknowledgment: {
          schema_version: 1,
          disclaimer_id: draftDisclaimer.disclaimer_id,
          disclaimer_text_hash: draftDisclaimer.text_hash,
          accepted_at: new Date().toISOString(),
          principal_id: principalId,
          action: "gtm.email_draft",
        },
      });
      setLastQueued(queued);
      setActiveTaskId(queued.task_id);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(null);
      setShowDisclaimer(false);
    }
  }

  async function handleTier3WithDisclaimer() {
    const selectedCredentialId = pendingTier3 ? tier3Credentials[pendingTier3] : "";
    if (!session || !pendingTier3 || !pendingDisclaimer || !principalId || !selectedCredentialId) {
      return;
    }
    const spec = TIER3_ACTIONS.find((item) => item.action === pendingTier3);
    if (!spec) {
      return;
    }

    setLoading(`Launching ${pendingTier3}`);
    setError("");
    const idempotencyKey = newIdempotencyKey();
    try {
      const input =
        pendingTier3 === "gtm.email_send"
          ? {
              to: "prospect@example.com",
              subject: selectedSendArtifactId ? "" : "Ajenda autonomy send proof",
              body: selectedSendArtifactId ? "" : "Tier 3 informed autonomy launch from Tasks UI.",
              ...(selectedSendArtifactId ? { artifact_id: selectedSendArtifactId } : {}),
            }
          : {
              record_type: "contact",
              data: { email: "prospect@example.com", firstname: "Prospect" },
            };

      const queued = await launchTask(
        session,
        {
          action: pendingTier3,
          mission_id: missionId || undefined,
          input,
          idempotency_key: idempotencyKey,
          credential_reference: (() => {
            const credential = credentials.find((item) => item.credential_id === selectedCredentialId);
            if (!credential) {
              throw new Error("Selected credential not found.");
            }
            return credentialReference(credential);
          })(),
          autonomy_acknowledgment: {
            schema_version: 1,
            disclaimer_id: pendingDisclaimer.disclaimer_id,
            disclaimer_text_hash: pendingDisclaimer.text_hash,
            accepted_at: new Date().toISOString(),
            principal_id: principalId,
            action: pendingTier3,
            side_effect_class: pendingTier3 === "gtm.email_send" ? "external_send" : "external_write",
          },
        },
        { idempotencyKey },
      );
      setLastQueued(queued);
      setActiveTaskId(queued.task_id);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(null);
      setShowDisclaimer(false);
      setPendingTier3(null);
    }
  }

  function openTier3Disclaimer(action: Tier3Action) {
    const options = credentialOptionsFor(action);
    if (options.length === 0) {
      setError(`Connect a credential for ${action} on the Credentials page first.`);
      return;
    }
    if (!tier3Credentials[action]) {
      setTier3Credentials((current) => ({
        ...current,
        [action]: options[0]?.credential_id ?? "",
      }));
    }
    setPendingTier3(action);
    setShowDisclaimer(true);
  }

  async function handleBrainMission(template: BrainMissionTemplate) {
    if (!session) {
      return;
    }
    if (template.capstone) {
      setActiveCapstone(template);
      void handleRefreshReviewQueue();
      return;
    }
    setLoading(`Launching ${template.action}`);
    setError("");
    try {
      const optionalCredential =
        template.requiresCredential && template.provider
          ? credentialForAction(template.action, template.provider)
          : null;
      const queued = await launchTask(session, {
        action: template.action,
        input: template.input,
        mission_id: missionId || undefined,
        idempotency_key: newIdempotencyKey(),
        ...(optionalCredential ? { credential_reference: credentialReference(optionalCredential) } : {}),
      });
      setLastQueued(queued);
      setActiveTaskId(queued.task_id);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(null);
    }
  }

  async function handleCapabilityCheck() {
    if (!session) {
      return;
    }
    setLoading("Running brain capability check");
    setError("");
    try {
      setCapabilityReport(await getBrainCapabilityCheck(session));
    } catch (err) {
      setError(err);
    } finally {
      setLoading(null);
    }
  }

  async function handleRefreshReviewQueue() {
    if (!session) {
      return;
    }
    setLoading("Loading review queue");
    setError("");
    try {
      const [pending, approved] = await Promise.all([
        listReviewQueue(session, { status: "pending", limit: 10 }),
        listReviewQueue(session, { status: "approved", limit: 10 }),
      ]);
      setReviewQueue(pending.items);
      setApprovedArtifacts(approved.items);
      if (!selectedSendArtifactId && approved.items[0]?.artifact_id) {
        setSelectedSendArtifactId(approved.items[0].artifact_id);
      }
    } catch (err) {
      setError(err);
    } finally {
      setLoading(null);
    }
  }

  async function handleCapstoneStep(step: BrainMissionCapstoneStep) {
    if (!session || !step) {
      return;
    }
    if (step.action === "review_queue") {
      await handleRefreshReviewQueue();
      return;
    }
    setLoading(`Capstone step ${step.step}: ${step.label}`);
    setError("");
    try {
      const optionalCredential =
        step.requiresCredential && step.provider
          ? credentialForAction(step.action, step.provider)
          : null;
      const stepInput =
        step.action === "gtm.email_send" && selectedSendArtifactId
          ? { ...step.input, artifact_id: selectedSendArtifactId, subject: "", body: "" }
          : step.input;
      const queued = await launchTask(session, {
        action: step.action,
        input: stepInput,
        mission_id: missionId || undefined,
        idempotency_key: newIdempotencyKey(),
        ...(optionalCredential ? { credential_reference: credentialReference(optionalCredential) } : {}),
      });
      setLastQueued(queued);
      setActiveTaskId(queued.task_id);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(null);
    }
  }

  async function handleApproveDraft(artifactId: string) {
    if (!session) {
      return;
    }
    setLoading(`Approving ${artifactId}`);
    setError("");
    try {
      await approveReviewQueueItem(session, artifactId);
      setReviewQueue((current) => current.filter((item) => item.artifact_id !== artifactId));
    } catch (err) {
      setError(err);
    } finally {
      setLoading(null);
    }
  }

  async function handleProof(proof: (typeof PROOF_BUTTONS)[number]["key"]) {
    if (!session) return;
    setLoading(`Launching ${proof}`);
    setError("");
    try {
      const queued = await launchProof(session, proof);
      setLastQueued(queued);
      setActiveTaskId(queued.task_id);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(null);
    }
  }

  return (
    <main className="page-shell">
      <section className="hero compact-hero">
        <div>
          <p className="eyebrow">Runtime tasks</p>
          <h1>{missionId ? "Launch mission abilities" : "Launch worker proofs"}</h1>
          <p>
            Queue ability-runtime tasks and monitor status, lineage, and evidence from your tenant session.
          </p>
        </div>
      </section>

      {missionId ? (
        <section className="panel">
          <div className="mission-context-banner">
            <div className="panel-heading-row">
              <strong>Mission scope active</strong>
              <Link className="ghost-link" to="/missions">
                ← All missions
              </Link>
            </div>
            <p className="muted">
              Tasks launched here attach to mission <code>{missionId}</code> and must stay inside its allowed
              abilities.
            </p>
          </div>
          <h2>Mission abilities</h2>
          <div className="card-grid two-up">
            {MISSION_ABILITY_PRESETS.map((preset) => (
              <button
                className="proof-card"
                key={preset.action}
                type="button"
                onClick={() => void handleMissionAbility(preset)}
                disabled={!session || loading !== null}
              >
                <strong>{preset.title}</strong>
                <span>{preset.description}</span>
              </button>
            ))}
          </div>
        </section>
      ) : null}

      {!missionId ? (
        <section className="panel">
          <BrainMissionsPanel
            templates={brainMissionTemplates}
            sessionReady={Boolean(session)}
            loading={loading !== null}
            capabilityReport={capabilityReport}
            onLaunch={(template) => void handleBrainMission(template)}
            onCapabilityCheck={() => void handleCapabilityCheck()}
          />
          <ReviewQueuePanel
            reviewQueue={reviewQueue}
            approvedArtifacts={approvedArtifacts}
            activeCapstone={activeCapstone}
            selectedSendArtifactId={selectedSendArtifactId}
            sessionReady={Boolean(session)}
            loading={loading !== null}
            onRefresh={() => void handleRefreshReviewQueue()}
            onApprove={(artifactId) => void handleApproveDraft(artifactId)}
            onCapstoneStep={(step) => void handleCapstoneStep(step)}
            onCloseCapstone={() => setActiveCapstone(null)}
            onSelectSendArtifact={setSelectedSendArtifactId}
          />
        </section>
      ) : null}

      <section className="panel">
        <h2>Proof launchers</h2>
        <div className="card-grid two-up">
          {PROOF_BUTTONS.map((proof) => (
            <button
              className="proof-card"
              key={proof.key}
              type="button"
              onClick={() => void handleProof(proof.key)}
              disabled={!session || loading !== null}
            >
              <strong>{proof.title}</strong>
              <span>{proof.description}</span>
            </button>
          ))}
        </div>
      </section>

      <Tier3AutonomyPanel
        autonomyMode={autonomyMode}
        principalId={principalId}
        credentials={credentials}
        tier3Credentials={tier3Credentials}
        approvedArtifactIds={approvedArtifacts}
        selectedSendArtifactId={selectedSendArtifactId}
        sessionReady={Boolean(session)}
        loading={loading !== null}
        hasDraftDisclaimer={Boolean(draftDisclaimer)}
        onDraftDisclaimer={() => {
          setPendingTier3(null);
          setShowDisclaimer(true);
        }}
        onTier3CredentialChange={(action, credentialId) =>
          setTier3Credentials((current) => ({
            ...current,
            [action]: credentialId,
          }))
        }
        onOpenTier3Disclaimer={openTier3Disclaimer}
        onSelectSendArtifact={setSelectedSendArtifactId}
      />

      <TaskMonitor
        activeTaskId={activeTaskId}
        lastQueued={lastQueued}
        taskStatus={taskStatus}
        sessionReady={Boolean(session)}
        loading={loading !== null}
        onTaskIdChange={setActiveTaskId}
        onRefresh={async () => {
          if (!session || !activeTaskId) return;
          setLoading("Refreshing task");
          try {
            setTaskStatus(await getTaskStatus(session, activeTaskId));
          } catch (err) {
            setError(err);
          } finally {
            setLoading(null);
          }
        }}
      />

      {loading ? <div className="toast">Working: {loading}</div> : null}
      {error ? (
        <PageErrorAlert error={error} />
      ) : null}

      {(pendingDisclaimer ?? draftDisclaimer) ? (
        <DisclaimerModal
          disclaimer={(pendingDisclaimer ?? draftDisclaimer)!}
          open={showDisclaimer}
          onCancel={() => {
            setShowDisclaimer(false);
            setPendingTier3(null);
          }}
          onConfirm={() =>
            void (pendingTier3 ? handleTier3WithDisclaimer() : handleDraftWithDisclaimer())
          }
        />
      ) : null}
    </main>
  );
}