import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getGmailOAuthAuthorizeUrl,
  getGoogleCalendarOAuthAuthorizeUrl,
  getGoogleContactsOAuthAuthorizeUrl,
  getGoogleDocsOAuthAuthorizeUrl,
  listProviderCredentials,
  revokeProviderCredential,
} from "../../api/client";
import type { AccountOnboardingResponse, ConnectorId, CustomerSession, ProviderCredentialResponse } from "../../types";
import IntegrationCard from "../ui/IntegrationCard";
import PageErrorAlert from "../PageErrorAlert";

const CONNECTORS: Array<{ id: ConnectorId; name: string; credentialId: string; description: string }> = [
  { id: "gmail", name: "Gmail", credentialId: "gmail-email", description: "Read inbox context and prepare or send email when allowed." },
  { id: "google_calendar", name: "Google Calendar", credentialId: "google-calendar-read", description: "Read your calendar for planning and briefings." },
  { id: "google_contacts", name: "Google Contacts", credentialId: "google-contacts-read", description: "Read contacts when a mission explicitly needs them." },
  { id: "google_docs", name: "Google Drive & Docs", credentialId: "google-docs", description: "Read a Google Doc you identify. Document discovery and editing are not implied." },
];

type ConnectorGridProps = { session: CustomerSession; onboarding?: AccountOnboardingResponse | null };

export default function ConnectorGrid({ session, onboarding }: ConnectorGridProps) {
  const [credentials, setCredentials] = useState<ProviderCredentialResponse[]>([]);
  const [busy, setBusy] = useState<ConnectorId | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [message, setMessage] = useState("");
  const popupRef = useRef<Window | null>(null);
  const canManage = onboarding?.can_manage_connections ?? true;

  const refresh = useCallback(async () => {
    const response = await listProviderCredentials(session);
    setCredentials(response.credentials);
  }, [session]);

  useEffect(() => {
    void refresh().catch(setError);
  }, [refresh]);

  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(() => {
      if (popupRef.current?.closed) {
        popupRef.current = null;
        setBusy(null);
      }
    }, 500);
    const timeout = window.setTimeout(() => setBusy(null), 5 * 60 * 1000);
    return () => {
      window.clearInterval(timer);
      window.clearTimeout(timeout);
    };
  }, [busy]);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || event.data.type !== "ajenda.connector.oauth.complete") return;
      const integration = event.data.integration as ConnectorId;
      if (CONNECTORS.some((connector) => connector.id === integration)) {
        setBusy(null);
        if (event.data.success) {
          setMessage(`${CONNECTORS.find((connector) => connector.id === integration)?.name ?? integration} connected.`);
          void refresh().catch(setError);
        } else {
          setMessage("Permission wasn't granted. The connector is still disconnected.");
        }
      }
    }
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [refresh]);

  const connectedById = useMemo(() => {
    const map = { ...(onboarding?.connections ?? {}) } as Record<string, boolean>;
    for (const credential of credentials) {
      if (credential.integration in map) {
        map[credential.integration] = credential.enabled && !credential.revoked && !credential.uses_platform_master_key;
      }
    }
    return map;
  }, [credentials, onboarding]);

  async function connect(connector: (typeof CONNECTORS)[number]) {
    if (busy) return;
    const popup = window.open("about:blank", "ajendaConnectorOAuth", "popup,width=520,height=720");
    popupRef.current = popup;
    setBusy(connector.id);
    setError(null);
    try {
      let response;
      if (connector.id === "gmail") response = await getGmailOAuthAuthorizeUrl(session, connector.credentialId);
      else if (connector.id === "google_calendar") response = await getGoogleCalendarOAuthAuthorizeUrl(session, connector.credentialId);
      else if (connector.id === "google_contacts") response = await getGoogleContactsOAuthAuthorizeUrl(session, connector.credentialId);
      else response = await getGoogleDocsOAuthAuthorizeUrl(session, connector.credentialId);
      if (popup) {
        popup.location.href = response.authorization_url;
        popup.focus();
      } else {
        window.location.assign(response.authorization_url);
      }
    } catch (err) {
      popup?.close();
      setError(err);
      setBusy(null);
    }
  }

  async function disconnect(connector: (typeof CONNECTORS)[number]) {
    if (!window.confirm(`Disconnect ${connector.name}? Ajenda will stop using this connection.`)) return;
    setBusy(connector.id);
    try {
      await revokeProviderCredential(session, connector.credentialId);
      await refresh();
      setMessage(`${connector.name} disconnected.`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section aria-labelledby="connector-grid-title">
      <h2 id="connector-grid-title">Connect your tools</h2>
      <p className="muted">Each connection is separate and optional. Signing into Ajenda with Google does not connect any of these tools.</p>
      {message ? <p className="success-banner" role="status">{message}</p> : null}
      <PageErrorAlert error={error} className="notice error" />
      <div className="cc-integration-grid">
        {CONNECTORS.map((connector) => {
          const connected = Boolean(connectedById[connector.id]);
          const disabled = !canManage || busy !== null;
          return (
            <IntegrationCard key={connector.id} name={connector.name} description={connector.description} status={connected ? "connected" : "connect"} disabled={disabled}>
              <button type="button" className="primary-button" disabled={disabled} onClick={() => void (connected ? disconnect(connector) : connect(connector))}>
                {busy === connector.id ? (connected ? "Disconnecting…" : "Opening Google…") : connected ? "Disconnect" : `Connect ${connector.name}`}
              </button>
              {!canManage ? <small className="muted">An owner or admin manages connections.</small> : null}
            </IntegrationCard>
          );
        })}
      </div>
    </section>
  );
}
