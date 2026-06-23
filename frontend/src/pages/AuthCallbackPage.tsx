import { FormEvent, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { completeOidcLogin } from "../api/client";
import {
  clearOidcTransientState,
  consumeOidcReturnPath,
  describeMissingCallbackParams,
  oidcRedirectUri,
  resolveCodeVerifier,
} from "../auth/oidc";
import { saveSession, sessionFromOidcResponse } from "../auth/session";
import type { ApiFailure, OidcTenantChoice } from "../types";
import { failureText } from "../utils/errors";

interface PendingCallback {
  code: string;
  loginIntentId: string;
  codeVerifier: string;
}

function parseTenantChoices(error: unknown): OidcTenantChoice[] {
  const failure = error as Partial<ApiFailure>;
  const body = failure.body;
  if (typeof body !== "object" || body === null || !("detail" in body)) {
    return [];
  }
  const detail = (body as { detail: unknown }).detail;
  if (typeof detail !== "object" || detail === null || !("tenants" in detail)) {
    return [];
  }
  const tenants = (detail as { tenants: unknown }).tenants;
  if (!Array.isArray(tenants)) {
    return [];
  }
  return tenants.filter(
    (item): item is OidcTenantChoice =>
      typeof item === "object" &&
      item !== null &&
      typeof (item as OidcTenantChoice).tenant_id === "string" &&
      typeof (item as OidcTenantChoice).org_name === "string" &&
      typeof (item as OidcTenantChoice).slug === "string",
  );
}

export default function AuthCallbackPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const callbackKey = `${searchParams.get("state") ?? ""}:${searchParams.get("code") ?? ""}:${searchParams.get("error") ?? ""}`;
  const handledKeyRef = useRef<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [tenantChoices, setTenantChoices] = useState<OidcTenantChoice[]>([]);
  const [selectedTenantId, setSelectedTenantId] = useState("");
  const [pendingCallback, setPendingCallback] = useState<PendingCallback | null>(null);

  async function finishLogin(callback: PendingCallback, tenantId?: string) {
    setLoading(true);
    setError("");
    setTenantChoices([]);

    try {
      const response = await completeOidcLogin({
        login_intent_id: callback.loginIntentId,
        code: callback.code,
        code_verifier: callback.codeVerifier,
        redirect_uri: oidcRedirectUri(),
        tenant_id: tenantId,
      });
      clearOidcTransientState(callback.loginIntentId);
      saveSession(sessionFromOidcResponse(response));
      navigate(consumeOidcReturnPath(callback.loginIntentId), { replace: true });
    } catch (err) {
      const choices = parseTenantChoices(err);
      if (choices.length > 0) {
        setPendingCallback(callback);
        setTenantChoices(choices);
        setSelectedTenantId(choices[0]?.tenant_id ?? "");
        setLoading(false);
        return;
      }
      setError(failureText(err));
      setLoading(false);
    }
  }

  useEffect(() => {
    if (handledKeyRef.current === callbackKey) {
      return;
    }
    handledKeyRef.current = callbackKey;

    let cancelled = false;

    async function handleCallback() {
      const oauthError = searchParams.get("error");
      if (oauthError) {
        if (!cancelled) {
          clearOidcTransientState(searchParams.get("state"));
          setError(
            oauthError === "access_denied"
              ? "Google sign-in was cancelled. Try again when you are ready."
              : `Identity provider error: ${oauthError}`,
          );
          setLoading(false);
        }
        return;
      }

      const code = searchParams.get("code");
      const loginIntentId = searchParams.get("state");
      const codeVerifier = resolveCodeVerifier(loginIntentId);

      if (!code || !loginIntentId || !codeVerifier) {
        if (!cancelled) {
          setError(
            describeMissingCallbackParams({
              code,
              loginIntentId,
              codeVerifier,
            }),
          );
          setLoading(false);
        }
        return;
      }

      await finishLogin({ code, loginIntentId, codeVerifier });
    }

    void handleCallback();
    return () => {
      cancelled = true;
    };
  }, [callbackKey, navigate, searchParams]);

  async function handleTenantSubmit(event: FormEvent) {
    event.preventDefault();
    if (!pendingCallback || !selectedTenantId) {
      return;
    }
    await finishLogin(pendingCallback, selectedTenantId);
  }

  if (tenantChoices.length > 0 && pendingCallback) {
    return (
      <main className="page-shell narrow">
        <section className="panel auth-panel">
          <p className="eyebrow">Choose workspace</p>
          <h1>Select your organization</h1>
          <p>Your Google account is linked to multiple Ajenda workspaces. Pick the one you want to open.</p>

          <form className="form-grid" onSubmit={(event) => void handleTenantSubmit(event)}>
            <label>
              Workspace
              <select
                value={selectedTenantId}
                onChange={(event) => setSelectedTenantId(event.target.value)}
                required
              >
                {tenantChoices.map((choice) => (
                  <option key={choice.tenant_id} value={choice.tenant_id}>
                    {choice.org_name} ({choice.slug})
                  </option>
                ))}
              </select>
            </label>
            <button type="submit" disabled={loading || !selectedTenantId}>
              {loading ? "Signing in..." : "Continue"}
            </button>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className="page-shell narrow">
      <section className="panel auth-panel">
        <p className="eyebrow">Signing you in</p>
        <h1>{loading ? "Completing sign-in" : "Sign-in failed"}</h1>
        {loading ? (
          <p>Verifying your Google session and linking your workspace…</p>
        ) : (
          <>
            <p>{error || "Something went wrong during sign-in."}</p>
            <div className="button-row">
              <Link className="primary-link" to="/signin">
                Try again
              </Link>
              {error.includes("No Ajenda account") ? (
                <Link className="ghost-link" to="/signup">
                  Create account
                </Link>
              ) : null}
              {error.includes("not verified") ? (
                <Link className="ghost-link" to="/verify-email">
                  Verify email
                </Link>
              ) : null}
            </div>
          </>
        )}
      </section>
    </main>
  );
}