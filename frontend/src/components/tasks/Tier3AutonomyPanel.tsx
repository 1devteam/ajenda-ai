import type { ProviderCredentialResponse } from "../../types";

export type Tier3Action = "gtm.email_send" | "gtm.crm_upsert";

export const TIER3_ACTIONS: Array<{
  action: Tier3Action;
  title: string;
  description: string;
  provider: string;
  credentialType: string;
}> = [
  {
    action: "gtm.email_send",
    title: "Send email",
    description:
      "Tier 3 external send via Gmail OAuth, tenant SMTP (any host), or platform ajenda-email.",
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

type Tier3AutonomyPanelProps = {
  autonomyMode: "off" | "pilot" | "enforce";
  principalId: string;
  credentials: ProviderCredentialResponse[];
  tier3Credentials: Record<Tier3Action, string>;
  approvedArtifactIds: Array<{ artifact_id: string; artifact_type: string }>;
  selectedSendArtifactId: string;
  sessionReady: boolean;
  loading: boolean;
  hasDraftDisclaimer: boolean;
  onDraftDisclaimer: () => void;
  onTier3CredentialChange: (action: Tier3Action, credentialId: string) => void;
  onOpenTier3Disclaimer: (action: Tier3Action) => void;
  onSelectSendArtifact: (artifactId: string) => void;
};

export default function Tier3AutonomyPanel({
  autonomyMode,
  principalId,
  credentials,
  tier3Credentials,
  approvedArtifactIds,
  selectedSendArtifactId,
  sessionReady,
  loading,
  hasDraftDisclaimer,
  onDraftDisclaimer,
  onTier3CredentialChange,
  onOpenTier3Disclaimer,
  onSelectSendArtifact,
}: Tier3AutonomyPanelProps) {
  if (autonomyMode === "off") {
    return null;
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

  return (
    <section className="panel">
      <h2>Informed autonomy</h2>
      <p>
        Autonomy mode is <strong>{autonomyMode}</strong>. Disclaimers are recorded in audit when you launch governed
        actions. Principal: <code>{principalId || "loading…"}</code>
      </p>

      {hasDraftDisclaimer ? (
        <button
          type="button"
          className="primary-button"
          disabled={!sessionReady || loading || !principalId}
          onClick={onDraftDisclaimer}
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
                  disabled={options.length === 0 || loading}
                  onChange={(event) => onTier3CredentialChange(item.action, event.target.value)}
                >
                  {options.length === 0 ? <option value="">No credential connected</option> : null}
                  {options.map((credential) => (
                    <option key={credential.credential_id} value={credential.credential_id}>
                      {credential.credential_id}
                    </option>
                  ))}
                </select>
              </label>
              {item.action === "gtm.email_send" && approvedArtifactIds.length > 0 ? (
                <label>
                  Approved artifact (optional)
                  <select
                    value={selectedSendArtifactId}
                    disabled={loading}
                    onChange={(event) => onSelectSendArtifact(event.target.value)}
                  >
                    <option value="">Send without artifact_id</option>
                    {approvedArtifactIds.map((artifact) => (
                      <option key={artifact.artifact_id} value={artifact.artifact_id}>
                        {artifact.artifact_type} — {artifact.artifact_id}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              <button
                type="button"
                className="ghost-button"
                disabled={!sessionReady || loading || options.length === 0 || !principalId}
                onClick={() => onOpenTier3Disclaimer(item.action)}
              >
                Launch with disclaimer
              </button>
            </div>
          );
        })}
      </div>
    </section>
  );
}