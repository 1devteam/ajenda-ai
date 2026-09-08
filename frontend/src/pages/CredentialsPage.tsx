import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import {
  connectGmailOAuth,
  connectGitHubOAuth,
  connectGoogleCalendarOAuth,
  connectGoogleContactsOAuth,
  connectGoogleDocsOAuth,
  connectLinkedInOAuth,
  connectSalesforceOAuth,
  createProviderCredential,
  deleteProviderCredential,
  getGmailOAuthAuthorizeUrl,
  getGitHubOAuthAuthorizeUrl,
  getGoogleCalendarOAuthAuthorizeUrl,
  getGoogleContactsOAuthAuthorizeUrl,
  getGoogleDocsOAuthAuthorizeUrl,
  getLinkedInOAuthAuthorizeUrl,
  getSalesforceOAuthAuthorizeUrl,
  listProviderCredentials,
  revokeProviderCredential,
} from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import PageErrorAlert from "../components/PageErrorAlert";
import ConnectorGrid from "../components/connections/ConnectorGrid";
import PageHeader from "../components/ui/PageHeader";
import type { ProviderCredentialCreateRequest, ProviderCredentialResponse } from "../types";


type IntegrationKind =
  | "hubspot"
  | "gmail"
  | "smtp"
  | "linkedin"
  | "salesforce"
  | "google_calendar"
  | "google_contacts"
  | "google_docs"
  | "github";

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

const SMTP_FORM: ProviderCredentialCreateRequest = {
  credential_id: "smtp-email",
  provider: "external_email",
  integration: "smtp",
  secret_value: "",
  use_platform_master_key: false,
};

type SmtpFormFields = {
  host: string;
  port: string;
  user: string;
  password: string;
  from: string;
  use_tls: boolean;
};

const EMPTY_SMTP_FIELDS: SmtpFormFields = {
  host: "",
  port: "587",
  user: "",
  password: "",
  from: "",
  use_tls: true,
};

function buildSmtpSecretJson(fields: SmtpFormFields): string {
  const host = fields.host.trim();
  const user = fields.user.trim();
  const password = fields.password;
  const port = Number.parseInt(fields.port.trim() || "587", 10);
  if (!host || !user || !password) {
    return "";
  }
  const payload: Record<string, unknown> = {
    host,
    port: Number.isFinite(port) ? port : 587,
    user,
    password,
    use_tls: fields.use_tls,
  };
  const from = fields.from.trim();
  if (from) {
    payload.from = from;
  }
  return JSON.stringify(payload);
}

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

const GOOGLE_CONTACTS_FORM: ProviderCredentialCreateRequest = {
  credential_id: "google-contacts-read",
  provider: "external_read_provider",
  integration: "google_contacts",
  secret_value: "",
  use_platform_master_key: false,
};

const GOOGLE_DOCS_FORM: ProviderCredentialCreateRequest = {
  credential_id: "google-docs",
  provider: "external_read_provider",
  integration: "google_docs",
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
  smtp: SMTP_FORM,
  linkedin: LINKEDIN_FORM,
  salesforce: SALESFORCE_FORM,
  google_calendar: GOOGLE_CALENDAR_FORM,
  google_contacts: GOOGLE_CONTACTS_FORM,
  google_docs: GOOGLE_DOCS_FORM,
  github: GITHUB_FORM,
};

const INTEGRATION_LABELS: Record<IntegrationKind, string> = {
  hubspot: "HubSpot CRM",
  gmail: "Gmail (Google)",
  smtp: "Email (SMTP)",
  linkedin: "LinkedIn",
  salesforce: "Salesforce",
  google_calendar: "Google Calendar",
  google_contacts: "Google Contacts",
  google_docs: "Google Drive & Docs",
  github: "GitHub",
};

/** Display order: Google connectors first, then other providers. */
const INTEGRATION_ORDER: IntegrationKind[] = [
  "gmail",
  "google_calendar",
  "google_contacts",
  "google_docs",
  "smtp",
  "hubspot",
  "salesforce",
  "linkedin",
  "github",
];

/**
 * In-memory guard for concurrent OAuth callback exchanges (React Strict Mode remounts
 * the same effect). sessionStorage alone is not enough: "in-flight" must not permanently
 * block a remount, but two parallel connect() calls with one code will fail the second.
 */
const oauthCallbackInFlight = new Set<string>();

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
  "/credentials/google-contacts/callback": {
    integration: "google_contacts",
    defaultCredentialId: "google-contacts-read",
    loadingLabel: "Connecting Google Contacts via OAuth",
    connect: connectGoogleContactsOAuth,
  },
  "/credentials/google-docs/callback": {
    integration: "google_docs",
    defaultCredentialId: "google-docs",
    loadingLabel: "Connecting Google Drive & Docs via OAuth",
    connect: connectGoogleDocsOAuth,
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
  const [smtpFields, setSmtpFields] = useState<SmtpFormFields>(EMPTY_SMTP_FIELDS);
  const [warning, setWarning] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [salesforceInstanceHost, setSalesforceInstanceHost] = useState("");

  useEffect(() => {
    setForm({ ...FORM_BY_INTEGRATION[integration] });
    if (integration !== "salesforce") {
      setSalesforceInstanceHost("");
    }
    if (integration !== "smtp") {
      setSmtpFields(EMPTY_SMTP_FIELDS);
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
    const callback = OAUTH_CALLBACKS[location.pathname];
    if (!callback) {
      return;
    }
    const params = new URLSearchParams(location.search);
    // Popup windows do not share sessionStorage with the authenticated opener.
    // Forward the one-time authorization result; the opener performs the exchange
    // with its own tenant session and the callback never handles credentials.
    if (!session) {
      const code = params.get("code");
      const state = params.get("state");
      const oauthError = params.get("error");
      if (window.opener && (code && state || oauthError)) {
        window.opener.postMessage(
          {
            type: "ajenda.connector.oauth.callback",
            integration: callback.integration,
            code,
            state,
            error: oauthError,
            error_description: params.get("error_description"),
          },
          window.location.origin,
        );
        window.close();
      }
      return;
    }
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
      setLoading(null);
      if (window.opener) {
        window.opener.postMessage({ type: "ajenda.connector.oauth.complete", integration: callback.integration, success: false }, window.location.origin);
        window.close();
      } else navigate("/credentials", { replace: true });
      return;
    }

    const code = params.get("code");
    const state = params.get("state");
    if (!code || !state) {
      return;
    }

    // Only skip completed exchanges in sessionStorage. In-memory set handles concurrent
    // Strict Mode remounts without permanently blocking a later legitimate retry.
    const oauthDedupeKey = `ajenda.oauth.callback:${location.pathname}:${state}`;
    if (window.sessionStorage.getItem(oauthDedupeKey) === "done") {
      setLoading(null);
      navigate("/credentials", { replace: true });
      return;
    }
    if (oauthCallbackInFlight.has(oauthDedupeKey)) {
      return;
    }
    oauthCallbackInFlight.add(oauthDedupeKey);

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
        window.sessionStorage.setItem(oauthDedupeKey, "done");
        if (response.warning) {
          setWarning(response.warning);
        }
        setIntegration(callback.integration);
        // Refresh list before navigate so React-preserved page state still has data.
        try {
          const listed = await listProviderCredentials(session!);
          setCredentials(listed.credentials);
        } catch (listErr) {
          // Connect succeeded; list failure should not keep the UI locked.
          if (!cancelled) {
            setError(listErr);
          }
        }
        if (window.opener) {
          window.opener.postMessage({ type: "ajenda.connector.oauth.complete", integration: callback.integration, success: true }, window.location.origin);
          window.close();
        } else navigate("/credentials", { replace: true });
      } catch (err) {
        window.sessionStorage.removeItem(oauthDedupeKey);
        // Always surface the error — Strict Mode cleanup sets cancelled=true and used
        // to swallow failures from the only in-flight exchange.
        setError(err);
        if (window.opener) {
          window.opener.postMessage({ type: "ajenda.connector.oauth.complete", integration: callback.integration, success: false }, window.location.origin);
          window.close();
        } else navigate("/credentials", { replace: true });
      } finally {
        oauthCallbackInFlight.delete(oauthDedupeKey);
        // Always clear loading. navigate() reuses CredentialsPage (same element type),
        // so effect cleanup sets cancelled=true and used to skip this — freezing all
        // connector buttons until a hard refresh.
        setLoading(null);
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
      if (integration === "smtp") {
        const secret = buildSmtpSecretJson(smtpFields);
        if (!secret) {
          setError(new Error("SMTP requires host, user/username, and password."));
          setLoading(null);
          return;
        }
        payload.secret_value = secret;
        payload.integration = "smtp";
        payload.provider = "external_email";
      }
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
      if (integration === "smtp") {
        setSmtpFields(EMPTY_SMTP_FIELDS);
      }
      await refreshList();
    } catch (err) {
      setError(err);
    } finally {
      setLoading(null);
    }
  }

  async function handleOAuthConnect(target: IntegrationKind = integration) {
    if (!session) {
      setError(
        new Error(
          "Sign in first, then use Connections to link Gmail, Calendar, or Contacts. Google sign-in alone does not connect those tools.",
        ),
      );
      return;
    }
    const label = INTEGRATION_LABELS[target];
    const credentialId = FORM_BY_INTEGRATION[target].credential_id;
    setIntegration(target);
    setLoading(`Starting ${label} OAuth`);
    setError(null);
    try {
      let response;
      if (target === "gmail") {
        response = await getGmailOAuthAuthorizeUrl(session, credentialId);
      } else if (target === "linkedin") {
        response = await getLinkedInOAuthAuthorizeUrl(session, credentialId);
      } else if (target === "salesforce") {
        response = await getSalesforceOAuthAuthorizeUrl(session, credentialId);
      } else if (target === "google_calendar") {
        response = await getGoogleCalendarOAuthAuthorizeUrl(session, credentialId);
      } else if (target === "google_contacts") {
        response = await getGoogleContactsOAuthAuthorizeUrl(session, credentialId);
      } else if (target === "google_docs") {
        response = await getGoogleDocsOAuthAuthorizeUrl(session, credentialId);
      } else if (target === "github") {
        response = await getGitHubOAuthAuthorizeUrl(session, credentialId);
      } else {
        throw new Error(`${label} does not support OAuth connect`);
      }
      if (!response?.authorization_url) {
        throw new Error(`${label} OAuth did not return an authorization URL from the API.`);
      }
      // Full-page redirect; if navigation is blocked, re-enable buttons.
      window.location.assign(response.authorization_url);
      window.setTimeout(() => {
        setLoading(null);
      }, 2500);
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
    integration === "google_contacts" ||
    integration === "google_docs" ||
    integration === "github";
  const submitLabel =
    integration === "hubspot"
      ? "Connect HubSpot CRM"
      : integration === "smtp"
        ? "Connect SMTP email"
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
    <main>
      <PageHeader
        eyebrow="Connections"
        title="Integrations and credentials"
        lead="Sign-in with Google only proves identity. Connect Gmail, Calendar, Contacts, or Drive & Docs here with separate OAuth consent when you need those tools."
      />

      <section className="panel">
        <h2>Google connectors</h2>
        {warning ? <p className="notice warning">{warning}</p> : null}
        <PageErrorAlert error={error} className="notice error" />
        {session ? <ConnectorGrid session={session} /> : null}
        <p className="field-hint" style={{ marginTop: "0.75rem" }}>
          Each connector uses separate Google OAuth consent from sign-in. Register redirect URIs
          <code> /credentials/google-calendar/callback </code> and
          <code> /credentials/google-contacts/callback </code> and
          <code> /credentials/google-docs/callback </code>
          on your Google Cloud OAuth client, and enable Calendar API, People API, and Google Docs API.
        </p>
      </section>

      <section className="panel">
        <h2>Advanced credential setup</h2>
        <p className="muted" style={{ marginTop: 0 }}>
          Paste tokens, SMTP, or non-Google providers. Prefer the Google connector buttons above when possible.
        </p>

        <div className="credential-tabs">
          {INTEGRATION_ORDER.map((kind) => (
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
          ) : (integration === "gmail" || integration === "smtp") && platformAjendaEmail ? (
            <p className="notice success">
              Platform email lane is included with Ajenda via ajenda-email ({platformAjendaEmail.credential_id},
              SMTP). Connect Gmail OAuth or your own SMTP below only if you want tenant-owned send credentials.
            </p>
          ) : null}

          {integration === "gmail" ? (
            <>
              <p className="muted">
                Gmail covers <strong>send</strong> and <strong>inbox read</strong> via Google OAuth. For non-Google
                mailboxes, use the Email (SMTP) tab for send only.
              </p>
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
          ) : integration === "smtp" ? (
            <>
              <p className="muted">
                SMTP works with Google Workspace app passwords, Microsoft 365, Amazon SES, SendGrid, Mailgun,
                Postmark, and any standard SMTP host. Powers <strong>gtm.email_send</strong> only — not inbox
                read.
              </p>
              <label>
                SMTP host
                <input
                  value={smtpFields.host}
                  onChange={(event) => setSmtpFields({ ...smtpFields, host: event.target.value })}
                  placeholder="smtp.example.com"
                  required
                />
              </label>
              <label>
                Port
                <input
                  value={smtpFields.port}
                  onChange={(event) => setSmtpFields({ ...smtpFields, port: event.target.value })}
                  placeholder="587"
                  inputMode="numeric"
                />
              </label>
              <label>
                Username
                <input
                  value={smtpFields.user}
                  onChange={(event) => setSmtpFields({ ...smtpFields, user: event.target.value })}
                  placeholder="sender@example.com"
                  required
                />
              </label>
              <label>
                Password / app password
                <input
                  type="password"
                  value={smtpFields.password}
                  onChange={(event) => setSmtpFields({ ...smtpFields, password: event.target.value })}
                  placeholder="App password or SMTP secret"
                  required
                />
              </label>
              <label>
                From address (optional)
                <input
                  value={smtpFields.from}
                  onChange={(event) => setSmtpFields({ ...smtpFields, from: event.target.value })}
                  placeholder="Defaults to username when empty"
                />
              </label>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={smtpFields.use_tls}
                  onChange={(event) => setSmtpFields({ ...smtpFields, use_tls: event.target.checked })}
                />
                Use STARTTLS (recommended on port 587)
              </label>
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
                  Prefer the Google Calendar connector button above. Manual paste is for CLI/E2E tokens only.
                </span>
              </label>
              <button
                type="button"
                className="ghost-button"
                disabled={loading !== null}
                onClick={() => void handleOAuthConnect("google_calendar")}
              >
                Connect Google Calendar with OAuth
              </button>
            </>
          ) : integration === "google_contacts" ? (
            <>
              <label>
                Google Contacts OAuth bearer or JSON bundle
                <textarea
                  value={form.secret_value ?? ""}
                  onChange={(event) => setForm({ ...form, secret_value: event.target.value })}
                  placeholder='Paste access token or JSON: {"provider_kind":"google_contacts","access_token":"...","refresh_token":"...","expires_at":"..."}'
                />
                <span className="field-hint">
                  Prefer the Google Contacts connector button above. OAuth requests contacts +
                  contacts.other.readonly.
                </span>
              </label>
              <button
                type="button"
                className="ghost-button"
                disabled={loading !== null}
                onClick={() => void handleOAuthConnect("google_contacts")}
              >
                Connect Google Contacts with OAuth
              </button>
            </>
          ) : integration === "github" ? (
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
          ) : null}

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
