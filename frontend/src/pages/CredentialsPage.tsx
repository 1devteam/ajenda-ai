import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  connectGmailOAuth,
  connectLinkedInOAuth,
  connectSalesforceOAuth,
  createProviderCredential,
  deleteProviderCredential,
  getGmailOAuthAuthorizeUrl,
  getLinkedInOAuthAuthorizeUrl,
  getSalesforceOAuthAuthorizeUrl,
  listProviderCredentials,
  revokeProviderCredential,
} from "../api/client";
import { loadSession } from "../auth/session";
import type { ProviderCredentialCreateRequest, ProviderCredentialResponse } from "../types";
import { failureText } from "../utils/errors";

type IntegrationKind = "hubspot" | "gmail" | "linkedin" | "salesforce";

const HUBSPOT_FORM: ProviderCredentialCreateRequest = {
  credential_id: "hubspot-crm",
  provider: "external_crm",
  integration: "hubspot",
  secret_value: "",
  use_platform_master_key: false,
};

const GMAIL_FORM: ProviderCredentialCreateRequest = {
  credential_id: "gmail-email",
  provider: "external_email",
  integration: "gmail",
  secret_value: "",
  use_platform_master_key: false,
};

const LINKEDIN_FORM: ProviderCredentialCreateRequest = {
  credential_id: "linkedin-read",
  provider: "external_read_provider",
  integration: "linkedin",
  secret_value: "",
  use_platform_master_key: false,
};

const SALESFORCE_FORM: ProviderCredentialCreateRequest = {
  credential_id: "salesforce-read",
  provider: "external_read_provider",
  integration: "salesforce",
  secret_value: "",
  use_platform_master_key: false,
};

const FORM_BY_INTEGRATION: Record<IntegrationKind, ProviderCredentialCreateRequest> = {
  hubspot: HUBSPOT_FORM,
  gmail: GMAIL_FORM,
  linkedin: LINKEDIN_FORM,
  salesforce: SALESFORCE_FORM,
};

const INTEGRATION_LABELS: Record<IntegrationKind, string> = {
  hubspot: "HubSpot CRM",
  gmail: "Gmail",
  linkedin: "LinkedIn",
  salesforce: "Salesforce",
};

const OAUTH_CALLBACKS: Record<
  string,
  {
    integration: IntegrationKind;
    defaultCredentialId: string;
    loadingLabel: string;
    connect: typeof connectGmailOAuth;
  }
> = {
  "/credentials/gmail/callback": {
    integration: "gmail",
    defaultCredentialId: "gmail-email",
    loadingLabel: "Connecting Gmail via OAuth",
    connect: connectGmailOAuth,
  },
  "/credentials/linkedin/callback": {
    integration: "linkedin",
    defaultCredentialId: "linkedin-read",
    loadingLabel: "Connecting LinkedIn via OAuth",
    connect: connectLinkedInOAuth,
  },
  "/credentials/salesforce/callback": {
    integration: "salesforce",
    defaultCredentialId: "salesforce-read",
    loadingLabel: "Connecting Salesforce via OAuth",
    connect: connectSalesforceOAuth,
  },
};

export default function CredentialsPage() {
  const session = loadSession();
  const location = useLocation();
  const navigate = useNavigate();
  const [integration, setIntegration] = useState<IntegrationKind>("hubspot");
  const [credentials, setCredentials] = useState<ProviderCredentialResponse[]>([]);
  const [form, setForm] = useState<ProviderCredentialCreateRequest>(HUBSPOT_FORM);
  const [warning, setWarning] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState<string | null>(null);

  useEffect(() => {
    setForm({ ...FORM_BY_INTEGRATION[integration] });
  }, [integration]);

  useEffect(() => {
    if (!session) {
      return;
    }
    let cancelled = false;
    async function load() {
      try {
        const response = await listProviderCredentials(session!);
        if (!cancelled) {
          setCredentials(response.credentials);
        }
      } catch (err) {
        if (!cancelled) {
          setError(failureText(err));
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [session?.tenantId, session?.apiKey, session?.accessToken]);

  useEffect(() => {
    if (!session) {
      return;
    }
    const callback = OAUTH_CALLBACKS[location.pathname];
    if (!callback) {
      return;
    }
    const params = new URLSearchParams(location.search);
    const code = params.get("code");
    const state = params.get("state");
    if (!code || !state) {
      return;
    }

    let cancelled = false;
    async function finishOAuth(oauthCode: string, oauthState: string) {
      setLoading(callback.loadingLabel);
      setError("");
      try {
        const response = await callback.connect(session!, {
          code: oauthCode,
          state: oauthState,
          credential_id: callback.defaultCredentialId,
        });
        if (!cancelled) {
          if (response.warning) {
            setWarning(response.warning);
          }
          setIntegration(callback.integration);
          navigate("/credentials", { replace: true });
          const listed = await listProviderCredentials(session!);
          setCredentials(listed.credentials);
        }
      } catch (err) {
        if (!cancelled) {
          setError(failureText(err));
          navigate("/credentials", { replace: true });
        }
      } finally {
        if (!cancelled) {
          setLoading(null);
        }
      }
    }
    void finishOAuth(code, state);
    return () => {
      cancelled = true;
    };
  }, [location.pathname, location.search, navigate, session]);

  async function refreshList() {
    if (!session) {
      return;
    }
    const response = await listProviderCredentials(session);
    setCredentials(response.credentials);
  }

  async function handleConnect(event: React.FormEvent) {
    event.preventDefault();
    if (!session) {
      return;
    }
    const label = INTEGRATION_LABELS[integration];
    setLoading(`Connecting ${label}`);
    setError("");
    setWarning("");
    try {
      const response = await createProviderCredential(session, form);
      if (response.warning) {
        setWarning(response.warning);
      }
      setForm({ ...FORM_BY_INTEGRATION[integration] });
      await refreshList();
    } catch (err) {
      setError(failureText(err));
    } finally {
      setLoading(null);
    }
  }

  async function handleOAuthConnect() {
    if (!session) {
      return;
    }
    const label = INTEGRATION_LABELS[integration];
    setLoading(`Starting ${label} OAuth`);
    setError("");
    try {
      let response;
      if (integration === "gmail") {
        response = await getGmailOAuthAuthorizeUrl(session, form.credential_id);
      } else if (integration === "linkedin") {
        response = await getLinkedInOAuthAuthorizeUrl(session, form.credential_id);
      } else {
        response = await getSalesforceOAuthAuthorizeUrl(session, form.credential_id);
      }
      window.location.assign(response.authorization_url);
    } catch (err) {
      setError(failureText(err));
      setLoading(null);
    }
  }

  async function handleRevoke(credentialId: string) {
    if (!session) {
      return;
    }
    setLoading(`Revoking ${credentialId}`);
    setError("");
    try {
      await revokeProviderCredential(session, credentialId);
      await refreshList();
    } catch (err) {
      setError(failureText(err));
    } finally {
      setLoading(null);
    }
  }

  async function handleDelete(credentialId: string) {
    if (!session) {
      return;
    }
    setLoading(`Deleting ${credentialId}`);
    setError("");
    try {
      await deleteProviderCredential(session, credentialId);
      await refreshList();
    } catch (err) {
      setError(failureText(err));
    } finally {
      setLoading(null);
    }
  }

  const supportsOAuth = integration === "gmail" || integration === "linkedin" || integration === "salesforce";
  const submitLabel =
    integration === "hubspot"
      ? "Connect HubSpot CRM"
      : supportsOAuth
        ? `Connect ${INTEGRATION_LABELS[integration]} (paste)`
        : `Connect ${INTEGRATION_LABELS[integration]}`;

  return (
    <main className="page-shell">
      <section className="panel">
        <h1>Provider credentials</h1>
        <p>
          Connect external CRM, email, and read providers for governed runtime actions. Secrets are encrypted per
          tenant and never returned after registration.
        </p>
        {warning ? <p className="notice warning">{warning}</p> : null}
        {error ? <p className="notice error">{error}</p> : null}

        <div className="credential-tabs">
          {(Object.keys(INTEGRATION_LABELS) as IntegrationKind[]).map((kind) => (
            <button
              key={kind}
              type="button"
              className={`credential-tab ${integration === kind ? "active" : ""}`}
              onClick={() => setIntegration(kind)}
            >
              {INTEGRATION_LABELS[kind]}
            </button>
          ))}
        </div>

        <form className="stack-form" onSubmit={handleConnect}>
          <label>
            Credential ID
            <input
              value={form.credential_id}
              onChange={(event) => setForm({ ...form, credential_id: event.target.value })}
              required
            />
          </label>

          {integration === "hubspot" ? (
            <>
              <label>
                HubSpot personal access key
                <input
                  type="password"
                  value={form.secret_value ?? ""}
                  disabled={form.use_platform_master_key}
                  onChange={(event) => setForm({ ...form, secret_value: event.target.value })}
                  placeholder="Paste HubSpot PAK (Bearer token)"
                />
              </label>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={form.use_platform_master_key}
                  onChange={(event) =>
                    setForm({
                      ...form,
                      use_platform_master_key: event.target.checked,
                      secret_value: event.target.checked ? "" : form.secret_value,
                    })
                  }
                />
                Use platform master key (operator-managed; shared blast radius)
              </label>
            </>
          ) : integration === "gmail" ? (
            <>
              <label>
                Gmail OAuth bearer or JSON bundle
                <textarea
                  value={form.secret_value ?? ""}
                  onChange={(event) => setForm({ ...form, secret_value: event.target.value })}
                  placeholder='Paste access token or JSON: {"access_token":"...","refresh_token":"...","expires_at":"..."}'
                />
                <span className="field-hint">
                  Or connect with Google below. Manual paste still works for CLI tokens from{" "}
                  <code>python scripts/google/gmail_cli_auth.py auth</code>.
                </span>
              </label>
              <button
                type="button"
                className="ghost-button"
                disabled={loading !== null}
                onClick={() => void handleOAuthConnect()}
              >
                Connect Gmail with Google
              </button>
            </>
          ) : integration === "linkedin" ? (
            <>
              <label>
                LinkedIn OAuth bearer or JSON bundle
                <textarea
                  value={form.secret_value ?? ""}
                  onChange={(event) => setForm({ ...form, secret_value: event.target.value })}
                  placeholder='Paste access token or JSON: {"provider_kind":"linkedin","access_token":"...","refresh_token":"...","expires_at":"..."}'
                />
                <span className="field-hint">Or connect with LinkedIn below for OAuth refresh at runtime.</span>
              </label>
              <button
                type="button"
                className="ghost-button"
                disabled={loading !== null}
                onClick={() => void handleOAuthConnect()}
              >
                Connect LinkedIn with OAuth
              </button>
            </>
          ) : (
            <>
              <label>
                Salesforce OAuth bearer or JSON bundle
                <textarea
                  value={form.secret_value ?? ""}
                  onChange={(event) => setForm({ ...form, secret_value: event.target.value })}
                  placeholder='Paste access token or JSON: {"provider_kind":"salesforce","access_token":"...","refresh_token":"...","instance_url":"https://...","expires_at":"..."}'
                />
                <span className="field-hint">
                  Or connect with Salesforce below. Instance host is captured from the OAuth response.
                </span>
              </label>
              <button
                type="button"
                className="ghost-button"
                disabled={loading !== null}
                onClick={() => void handleOAuthConnect()}
              >
                Connect Salesforce with OAuth
              </button>
            </>
          )}

          <button type="submit" className="primary-button" disabled={loading !== null}>
            {loading ?? submitLabel}
          </button>
        </form>
      </section>

      <section className="panel">
        <h2>Stored credentials</h2>
        {credentials.length === 0 ? (
          <p>No provider credentials registered yet.</p>
        ) : (
          <ul className="credential-list">
            {credentials.map((item) => (
              <li key={item.credential_id} className="credential-card">
                <div>
                  <strong>{item.credential_id}</strong> · {item.provider} · {item.credential_type}
                </div>
                <div>hosts: {item.trusted_destination_hosts.join(", ") || "—"}</div>
                <div>actions: {item.allowed_actions.join(", ") || "—"}</div>
                {item.platform_master_warning ? (
                  <p className="notice warning">{item.platform_master_warning}</p>
                ) : null}
                <div className="inline-actions">
                  <button
                    type="button"
                    className="ghost-button"
                    disabled={item.revoked || loading !== null}
                    onClick={() => void handleRevoke(item.credential_id)}
                  >
                    Revoke
                  </button>
                  <button
                    type="button"
                    className="ghost-button"
                    disabled={loading !== null}
                    onClick={() => void handleDelete(item.credential_id)}
                  >
                    Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}