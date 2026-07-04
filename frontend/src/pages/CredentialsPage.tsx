import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  connectGmailOAuth,
  connectGitHubOAuth,
  connectGoogleCalendarOAuth,
  connectLinkedInOAuth,
  connectSalesforceOAuth,
  createProviderCredential,
  deleteProviderCredential,
  getGmailOAuthAuthorizeUrl,
  getGitHubOAuthAuthorizeUrl,
  getGoogleCalendarOAuthAuthorizeUrl,
  getLinkedInOAuthAuthorizeUrl,
  getSalesforceOAuthAuthorizeUrl,
  listProviderCredentials,
  revokeProviderCredential,
} from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import PageErrorAlert from "../components/PageErrorAlert";
import type { ProviderCredentialCreateRequest, ProviderCredentialResponse } from "../types";


type IntegrationKind = "hubspot" | "gmail" | "linkedin" | "salesforce" | "google_calendar" | "github";

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

const GOOGLE_CALENDAR_FORM: ProviderCredentialCreateRequest = {
  credential_id: "google-calendar-read",
  provider: "external_read_provider",
  integration: "google_calendar",
  secret_value: "",
  use_platform_master_key: false,
};

const GITHUB_FORM: ProviderCredentialCreateRequest = {
  credential_id: "github-read",
  provider: "external_read_provider",
  integration: "github",
  secret_value: "",
  use_platform_master_key: false,
};

const FORM_BY_INTEGRATION: Record<IntegrationKind, ProviderCredentialCreateRequest> = {
  hubspot: HUBSPOT_FORM,
  gmail: GMAIL_FORM,
  linkedin: LINKEDIN_FORM,
  salesforce: SALESFORCE_FORM,
  google_calendar: GOOGLE_CALENDAR_FORM,
  github: GITHUB_FORM,
};

const INTEGRATION_LABELS: Record<IntegrationKind, string> = {
  hubspot: "HubSpot CRM",
  gmail: "Gmail",
  linkedin: "LinkedIn",
  salesforce: "Salesforce",
  google_calendar: "Google Calendar",
  github: "GitHub",
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
  "/credentials/google-calendar/callback": {
    integration: "google_calendar",
    defaultCredentialId: "google-calendar-read",
    loadingLabel: "Connecting Google Calendar via OAuth",
    connect: connectGoogleCalendarOAuth,
  },
  "/credentials/github/callback": {
    integration: "github",
    defaultCredentialId: "github-read",
    loadingLabel: "Connecting GitHub via OAuth",
    connect: connectGitHubOAuth,
  },
};

export default function CredentialsPage() {
  const { session } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [integration, setIntegration] = useState<IntegrationKind>("gmail");
  const [credentials, setCredentials] = useState<ProviderCredentialResponse[]>([]);
  const [form, setForm] = useState<ProviderCredentialCreateRequest>(GMAIL_FORM);
  const [warning, setWarning] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [salesforceInstanceHost, setSalesforceInstanceHost] = useState("");

  useEffect(() => {
    setForm({ ...FORM_BY_INTEGRATION[integration] });
    if (integration !== "salesforce") {
      setSalesforceInstanceHost("");
    }
  }, [integration]);

  function parseSalesforceInstanceHost(secretValue: string): string {
    const trimmed = secretValue.trim();
    if (!trimmed.startsWith("{")) {
      return "";
    }
    try {
      const payload = JSON.parse(trimmed) as { instance_url?: unknown };
      if (typeof payload.instance_url !== "string") {
        return "";
      }
      return new URL(payload.instance_url).hostname;
    } catch {
      return "";
    }
  }

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
          setError(err);
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
    const oauthError = params.get("error");
    if (oauthError) {
      const description = params.get("error_description")?.trim();
      setError({
        status: 400,
        message: oauthError,
        body: {
          detail: description || oauthError,
          code: oauthError === "access_denied" ? "ACCESS_DENIED" : "OAUTH_ERROR",
        },
      });
      navigate("/credentials", { replace: true });
      return;
    }

    const code = params.get("code");
    const state = params.get("state");
    if (!code || !state) {
      return;
    }

    const oauthDedupeKey = `ajenda.oauth.callback:${location.pathname}:${state}`;
    if (window.sessionStorage.getItem(oauthDedupeKey)) {
      navigate("/credentials", { replace: true });
      return;
    }
    window.sessionStorage.setItem(oauthDedupeKey, "in-flight");

    let cancelled = false;
    async function finishOAuth(oauthCode: string, oauthState: string) {
      setLoading(callback.loadingLabel);
      setError(null);
      try {
        const response = await callback.connect(session!, {
          code: oauthCode,
          state: oauthState,
          credential_id: callback.defaultCredentialId,
        });
        if (!cancelled) {
          window.sessionStorage.setItem(oauthDedupeKey, "done");
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
          window.sessionStorage.removeItem(oauthDedupeKey);
          setError(err);
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
    setError(null);
    setWarning("");
    try {
      const payload: ProviderCredentialCreateRequest = { ...form };
      if (integration === "salesforce") {
        const derivedHost = parseSalesforceInstanceHost(form.secret_value ?? "");
        const host = (salesforceInstanceHost || derivedHost).trim();
        if (host) {
          payload.trusted_destination_hosts = [host];
        }
      }
      const response = await createProviderCredential(session, payload);
      if (response.warning) {
        setWarning(response.warning);
      }
      setForm({ ...FORM_BY_INTEGRATION[integration] });
      await refreshList();
    } catch (err) {
      setError(err);
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
    setError(null);
    try {
      let response;
      if (integration === "gmail") {
        response = await getGmailOAuthAuthorizeUrl(session, form.credential_id);
      } else if (integration === "linkedin") {
        response = await getLinkedInOAuthAuthorizeUrl(session, form.credential_id);
      } else if (integration === "salesforce") {
        response = await getSalesforceOAuthAuthorizeUrl(session, form.credential_id);
      } else if (integration === "google_calendar") {
        response = await getGoogleCalendarOAuthAuthorizeUrl(session, form.credential_id);
      } else {
        response = await getGitHubOAuthAuthorizeUrl(session, form.credential_id);
      }
      window.location.assign(response.authorization_url);
    } catch (err) {
      setError(err);
      setLoading(null);
    }
  }

  async function handleRevoke(credentialId: string) {
    if (!session) {
      return;
    }
    if (!window.confirm(`Revoke credential "${credentialId}"? Runtime actions using it will stop working.`)) {
      return;
    }
    setLoading(`Revoking ${credentialId}`);
    setError(null);
    try {
      await revokeProviderCredential(session, credentialId);
      await refreshList();
    } catch (err) {
      setError(err);
    } finally {
      setLoading(null);
    }
  }

  async function handleDelete(credentialId: string) {
    if (!session) {
      return;
    }
    if (!window.confirm(`Delete credential "${credentialId}" permanently? This cannot be undone.`)) {
      return;
    }
    setLoading(`Deleting ${credentialId}`);
    setError(null);
    try {
      await deleteProviderCredential(session, credentialId);
      await refreshList();
    } catch (err) {
      setError(err);
    } finally {
      setLoading(null);
    }
  }

  const supportsOAuth =
    integration === "gmail" ||
    integration === "linkedin" ||
    integration === "salesforce" ||
    integration === "google_calendar" ||
    integration === "github";
  const submitLabel =
    integration === "hubspot"
      ? "Connect HubSpot CRM"
      : supportsOAuth
        ? `Connect ${INTEGRATION_LABELS[integration]} (paste)`
        : `Connect ${INTEGRATION_LABELS[integration]}`;

  const platformHubspot = credentials.find(
    (item) => item.credential_id === "hubspot-crm" && item.uses_platform_master_key && !item.revoked,
  );
  const platformAjendaEmail = credentials.find(
    (item) => item.credential_id === "ajenda-email" && item.uses_platform_master_key && !item.revoked,
  );

  return (
    <main className="page-shell">
      <section className="panel">
        <h1>Plugins (optional)</h1>
        <p>
          Standalone brain missions run without plugins. Connect Gmail, HubSpot, Salesforce, and other adapters only
          when you need external systems. Secrets are encrypted per tenant and never returned after registration.
        </p>
        {warning ? <p className="notice warning">{warning}</p> : null}
        <PageErrorAlert error={error} className="notice error" />

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

          {integration === "hubspot" && platformHubspot ? (
            <p className="notice success">
              HubSpot CRM is already included with Ajenda via platform master key ({platformHubspot.credential_id}).
              Connect your own PAK below only if you want tenant-owned credentials.
            </p>
          ) : null}

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
          ) : integration === "gmail" && platformAjendaEmail ? (
            <p className="notice success">
              Platform email lane is included with Ajenda via ajenda-email ({platformAjendaEmail.credential_id}).
              Connect your own Gmail below only if you want tenant-owned credentials.
            </p>
          ) : null}

          {integration === "gmail" ? (
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
          ) : integration === "salesforce" ? (
            <>
              <label>
                Salesforce instance host
                <input
                  value={salesforceInstanceHost}
                  onChange={(event) => setSalesforceInstanceHost(event.target.value)}
                  placeholder="mycompany.my.salesforce.com"
                />
                <span className="field-hint">
                  Required for plain bearer tokens. OAuth connect and JSON bundles with{" "}
                  <code>instance_url</code> infer this automatically.
                </span>
              </label>
              <label>
                Salesforce OAuth bearer or JSON bundle
                <textarea
                  value={form.secret_value ?? ""}
                  onChange={(event) => {
                    const secretValue = event.target.value;
                    setForm({ ...form, secret_value: secretValue });
                    const derivedHost = parseSalesforceInstanceHost(secretValue);
                    if (derivedHost) {
                      setSalesforceInstanceHost(derivedHost);
                    }
                  }}
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
          ) : integration === "google_calendar" ? (
            <>
              <label>
                Google Calendar OAuth bearer or JSON bundle
                <textarea
                  value={form.secret_value ?? ""}
                  onChange={(event) => setForm({ ...form, secret_value: event.target.value })}
                  placeholder='Paste access token or JSON: {"provider_kind":"google_calendar","access_token":"...","refresh_token":"...","expires_at":"..."}'
                />
                <span className="field-hint">
                  Or connect with Google below. Reuses the same Google OAuth client as Gmail with calendar.readonly
                  scope.
                </span>
              </label>
              <button
                type="button"
                className="ghost-button"
                disabled={loading !== null}
                onClick={() => void handleOAuthConnect()}
              >
                Connect Google Calendar with OAuth
              </button>
            </>
          ) : (
            <>
              <label>
                GitHub OAuth bearer, PAT, or JSON bundle
                <textarea
                  value={form.secret_value ?? ""}
                  onChange={(event) => setForm({ ...form, secret_value: event.target.value })}
                  placeholder='Paste PAT or JSON: {"provider_kind":"github","access_token":"...","refresh_token":"...","expires_at":"..."}'
                />
                <span className="field-hint">
                  Or connect with GitHub below. OAuth app must enable expiring tokens for runtime refresh.
                </span>
              </label>
              <button
                type="button"
                className="ghost-button"
                disabled={loading !== null}
                onClick={() => void handleOAuthConnect()}
              >
                Connect GitHub with OAuth
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
                  {item.uses_platform_master_key ? (
                    <span className="status-pill included">Included with Ajenda</span>
                  ) : null}
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