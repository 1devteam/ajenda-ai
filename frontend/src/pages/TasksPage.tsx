import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import DisclaimerModal from "../components/DisclaimerModal";
import {
  getAccountMe,
  getTaskStatus,
  launchProof,
  launchTask,
  listAutonomyDisclaimers,
  listProviderCredentials,
} from "../api/client";
import { loadSession, sessionToRuntimeConfig } from "../auth/session";
import { MISSION_ABILITY_PRESETS, type MissionAbilityPreset } from "../config/missionAbilities";
import type {
  AbilityTaskQueuedResponse,
  AbilityTaskStatusResponse,
  AutonomyDisclaimer,
  ProviderCredentialResponse,
} from "../types";
import { failureText, newIdempotencyKey, pretty } from "../utils/errors";

const PROOF_BUTTONS = [
  { key: "calendar-read" as const, title: "Calendar Read", description: "Read-only calendar proof." },
  { key: "sales-qualify" as const, title: "Sales Qualify", description: "Qualify a sample roofing lead." },
] as const;

type Tier3Action = "gtm.email_send" | "gtm.crm_upsert";

const TIER3_ACTIONS: Array<{
  action: Tier3Action;
  title: string;
  description: string;
  provider: string;
  credentialType: string;
}> = [
  {
    action: "gtm.email_send",
    title: "Send email",
    description: "Tier 3 external send through connected Gmail.",
    provider: "external_email",
    credentialType: "api_key",
  },
  {
    action: "gtm.crm_upsert",
    title: "CRM upsert",
    description: "Tier 3 external write through connected HubSpot CRM.",
    provider: "external_crm",
    credentialType: "api_key",
  },
];

export default function TasksPage() {
  const [searchParams] = useSearchParams();
  const missionId = searchParams.get("mission_id")?.trim() ?? "";
  const session = loadSession();
  const config = useMemo(
    () => (session ? sessionToRuntimeConfig(session) : null),
    [session?.tenantId, session?.apiKey, session?.accessToken],
  );
  const [activeTaskId, setActiveTaskId] = useState("");
  const [taskStatus, setTaskStatus] = useState<AbilityTaskStatusResponse | null>(null);
  const [lastQueued, setLastQueued] = useState<AbilityTaskQueuedResponse | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState("");
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

  const draftDisclaimer = disclaimers.find((item) => item.actions.includes("gtm.email_draft")) ?? null;
  const pendingDisclaimer = pendingTier3
    ? disclaimers.find((item) => item.actions.includes(pendingTier3)) ?? null
    : null;

  useEffect(() => {
    if (!config || !session) {
      return;
    }
    let cancelled = false;
    async function loadAutonomyContext() {
      try {
        const [disclaimerResponse, account, credentialResponse] = await Promise.all([
          listAutonomyDisclaimers(config!),
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
      } catch {
        if (!cancelled) {
          setAutonomyMode("off");
        }
      }
    }
    void loadAutonomyContext();
    return () => {
      cancelled = true;
    };
  }, [config, session]);

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

  function credentialForPreset(preset: MissionAbilityPreset) {
    if (!preset.provider) {
      return "";
    }
    return (
      credentials.find(
        (item) =>
          item.provider === preset.provider &&
          item.allowed_actions.includes(preset.action) &&
          !item.revoked,
      )?.credential_id ?? ""
    );
  }

  async function handleMissionAbility(preset: MissionAbilityPreset) {
    if (!config || !missionId) {
      return;
    }
    if (preset.requiresCredential) {
      const credentialId = credentialForPreset(preset);
      if (!credentialId) {
        setError(`Connect a credential for ${preset.action} on the Credentials page first.`);
        return;
      }
      setLoading(`Launching ${preset.action}`);
      setError("");
      try {
        const queued = await launchTask(config, {
          action: preset.action,
          input: preset.input,
          mission_id: missionId,
          idempotency_key: newIdempotencyKey(),
          credential_reference: {
            schema_version: 1,
            credential_id: credentialId,
            provider: preset.provider!,
            credential_type: preset.credentialType ?? "api_key",
          },
        });
        setLastQueued(queued);
        setActiveTaskId(queued.task_id);
      } catch (err) {
        setError(failureText(err));
      } finally {
        setLoading(null);
      }
      return;
    }

    setLoading(`Launching ${preset.action}`);
    setError("");
    try {
      const queued = await launchTask(config, {
        action: preset.action,
        input: preset.input,
        mission_id: missionId,
        idempotency_key: newIdempotencyKey(),
      });
      setLastQueued(queued);
      setActiveTaskId(queued.task_id);
    } catch (err) {
      setError(failureText(err));
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
    if (!config || !draftDisclaimer || !principalId) {
      return;
    }
    setLoading("Launching email draft");
    setError("");
    try {
      const queued = await launchTask(config, {
        action: "gtm.email_draft",
        mission_id: missionId || undefined,
        input: {
          recipient: "prospect@example.com",
          topic: "Ajenda follow-up",
          tone: "professional",
          context: "Product runtime disclaimer path",
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
      setError(failureText(err));
    } finally {
      setLoading(null);
      setShowDisclaimer(false);
    }
  }

  async function handleTier3WithDisclaimer() {
    const selectedCredentialId = pendingTier3 ? tier3Credentials[pendingTier3] : "";
    if (!config || !pendingTier3 || !pendingDisclaimer || !principalId || !selectedCredentialId) {
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
              subject: "Ajenda autonomy send proof",
              body: "Tier 3 informed autonomy launch from Tasks UI.",
            }
          : {
              record_type: "contact",
              data: { email: "prospect@example.com", firstname: "Prospect" },
            };

      const queued = await launchTask(
        config,
        {
          action: pendingTier3,
          mission_id: missionId || undefined,
          input,
          idempotency_key: idempotencyKey,
          credential_reference: {
            schema_version: 1,
            credential_id: selectedCredentialId,
            provider: spec.provider,
            credential_type: spec.credentialType,
          },
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
      setError(failureText(err));
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
                disabled={!config || loading !== null}
              >
                <strong>{preset.title}</strong>
                <span>{preset.description}</span>
              </button>
            ))}
          </div>
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
              disabled={!config || loading !== null}
            >
              <strong>{proof.title}</strong>
              <span>{proof.description}</span>
            </button>
          ))}
        </div>
      </section>

      {autonomyMode !== "off" ? (
        <section className="panel">
          <h2>Informed autonomy</h2>
          <p>
            Autonomy mode is <strong>{autonomyMode}</strong>. Disclaimers are recorded in audit when you launch governed
            actions. Principal: <code>{principalId || "loading…"}</code>
          </p>

          {draftDisclaimer ? (
            <button
              type="button"
              className="primary-button"
              disabled={!config || loading !== null || !principalId}
              onClick={() => {
                setPendingTier3(null);
                setShowDisclaimer(true);
              }}
            >
              Draft email (Tier 1)
            </button>
          ) : null}

          <div className="card-grid two-up tier3-grid">
            {TIER3_ACTIONS.map((item) => {
              const options = credentialOptionsFor(item.action);
              return (
                <div className="proof-card static-card" key={item.action}>
                  <strong>{item.title}</strong>
                  <span>{item.description}</span>
                  <label>
                    Credential
                    <select
                      value={tier3Credentials[item.action]}
                      disabled={options.length === 0 || loading !== null}
                      onChange={(event) =>
                        setTier3Credentials((current) => ({
                          ...current,
                          [item.action]: event.target.value,
                        }))
                      }
                    >
                      {options.length === 0 ? <option value="">No credential connected</option> : null}
                      {options.map((credential) => (
                        <option key={credential.credential_id} value={credential.credential_id}>
                          {credential.credential_id}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    type="button"
                    className="ghost-button"
                    disabled={!config || loading !== null || options.length === 0 || !principalId}
                    onClick={() => openTier3Disclaimer(item.action)}
                  >
                    Launch with disclaimer
                  </button>
                </div>
              );
            })}
          </div>
        </section>
      ) : null}

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