import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  connectGmailOAuth,
  createProviderCredential,
  deleteProviderCredential,
  getGmailOAuthAuthorizeUrl,
  listProviderCredentials,
  revokeProviderCredential,
} from "../api/client";
import { loadSession } from "../auth/session";
import type { ProviderCredentialCreateRequest, ProviderCredentialResponse } from "../types";
import { failureText } from "../utils/errors";

type IntegrationKind = "hubspot" | "gmail";

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
    setForm(integration === "hubspot" ? { ...HUBSPOT_FORM } : { ...GMAIL_FORM });
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
    if (!session || !location.pathname.endsWith("/credentials/gmail/callback")) {
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
      setLoading("Connecting Gmail via OAuth");
      setError("");
      try {
        const response = await connectGmailOAuth(session!, {
          code: oauthCode,
          state: oauthState,
          credential_id: "gmail-email",
        });
        if (!cancelled) {
          if (response.warning) {
            setWarning(response.warning);
          }
          setIntegration("gmail");
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
    const label = integration === "hubspot" ? "HubSpot" : "Gmail";
    setLoading(`Connecting ${label}`);
    setError("");
    setWarning("");
    try {
      const response = await createProviderCredential(session, form);
      if (response.warning) {
        setWarning(response.warning);
      }
      setForm(integration === "hubspot" ? { ...HUBSPOT_FORM } : { ...GMAIL_FORM });
      await refreshList();
    } catch (err) {
      setError(failureText(err));
    } finally {
      setLoading(null);
    }
  }

  async function handleGmailOAuthConnect() {
    if (!session) {
      return;
    }
    setLoading("Starting Gmail OAuth");
    setError("");
    try {
      const response = await getGmailOAuthAuthorizeUrl(session, form.credential_id);
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

  return (
    <main className="page-shell">
      <section className="panel">
        <h1>Provider credentials</h1>
        <p>
          Connect external CRM and email plugins for governed runtime actions. Secrets are encrypted per tenant and
          never returned after registration.
        </p>
        {warning ? <p className="notice warning">{warning}</p> : null}
        {error ? <p className="notice error">{error}</p> : null}

        <div className="credential-tabs">
          <button
            type="button"
            className={`credential-tab ${integration === "hubspot" ? "active" : ""}`}
            onClick={() => setIntegration("hubspot")}
          >
            HubSpot CRM
          </button>
          <button
            type="button"
            className={`credential-tab ${integration === "gmail" ? "active" : ""}`}
            onClick={() => setIntegration("gmail")}
          >
            Gmail
          </button>
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
          ) : (
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
                onClick={() => void handleGmailOAuthConnect()}
              >
                Connect Gmail with Google
              </button>
            </>
          )}

          <button type="submit" className="primary-button" disabled={loading !== null}>
            {loading ?? (integration === "hubspot" ? "Connect HubSpot CRM" : "Connect Gmail (paste)")}
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