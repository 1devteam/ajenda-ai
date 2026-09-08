import {
  canRefreshSession,
  forceSignOut,
  isAuthenticationFailure,
  sessionExpiredFailure,
  shouldRefreshAccessToken,
} from "../auth/sessionLifecycle";
import {
  getApiBaseUrl,
  saveSession,
  sessionFromOidcResponse,
  sessionToRuntimeConfig,
} from "../auth/session";
import { newIdempotencyKey } from "../utils/errors";
import type {
  AbilityActionListResponse,
  AutonomyDisclaimerListResponse,
  BrainCapabilityCheckResponse,
  BrainMissionListResponse,
  CrmPipelineResponse,
  CrmRecordItem,
  CrmRecordListResponse,
  CrmRecordWriteRequest,
  CrmRelationshipResponse,
  CrmSuggestionsResponse,
  CrmTimelineResponse,
  ReviewQueueListResponse,
  ReviewQueueItem,
  AbilityTaskCreate,
  AbilityTaskQueuedResponse,
  AbilityTaskStatusResponse,
  BridgeRuntimeAuthorityReadResponse,
  GraphMaterializationReadResponse,
  GraphMaterializationWriteRequest,
  MissionComposeConfirmResponse,
  MissionComposeResponse,
  MissionCreateRequest,
  MissionLifecycleReadResponse,
  MissionListResponse,
  MissionPlanCreateRequest,
  MissionPlanReadResponse,
  MissionReadResponse,
  MissionTaskGraphPayload,
  MissionTaskGraphReadResponse,
  RuntimeAdmissionReadResponse,
  RuntimeAdmissionWriteRequest,
  RuntimeDispatchReadinessReadResponse,
  RuntimeQueueAdmissionResponse,
  RuntimeReadinessReadResponse,
  RuntimeTaskMaterializationReadResponse,
  AccountBillingResponse,
  AccountOnboardingResponse,
  AccountMeResponse,
  AccountPlanResponse,
  AccountUsageResponse,
  GmailOAuthAuthorizeUrlResponse,
  GmailOAuthConnectRequest,
  ProviderCredentialCreateRequest,
  ProviderCredentialCreateResponse,
  ProviderCredentialListResponse,
  ProviderCredentialResponse,
  ApiFailure,
  CheckoutResponse,
  CustomerSession,
  CustomerSessionResponse,
  OidcConfigResponse,
  PasswordLoginRequest,
  PortalResponse,
  PromoteBootstrapKeyResponse,
  RuntimeConfig,
  ResendVerificationResponse,
  SignupRequest,
  SignupResponse,
  VerifyEmailResponse,
  BusinessProfileFactUpsertRequest,
  BusinessProfileReadResponse,
} from "../types";

async function parseBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) {
    return null;
  }

  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function endpoint(baseUrl: string, path: string): string {
  const base = baseUrl.trim().replace(/\/+$/, "");
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${base}${normalized}`;
}

function requireTenantCredentials(options: {
  tenantId?: string;
  apiKey?: string;
  accessToken?: string;
  authMode?: RuntimeConfig["authMode"];
}): { tenantId: string; apiKey?: string; accessToken?: string; authMode: "oidc" | "api_key" } {
  const tenantId = options.tenantId?.trim() ?? "";
  const authMode = options.authMode === "oidc" ? "oidc" : "api_key";

  if (!tenantId) {
    throw missingSessionFailure();
  }

  if (authMode === "oidc") {
    const accessToken = options.accessToken?.trim() ?? "";
    if (!accessToken) {
      throw missingSessionFailure();
    }
    return { tenantId, accessToken, authMode };
  }

  const apiKey = options.apiKey?.trim() ?? "";
  if (!apiKey) {
    throw missingSessionFailure();
  }
  return { tenantId, apiKey, authMode };
}

function missingSessionFailure(): ApiFailure {
  return {
    status: 0,
    message: "Missing tenant session",
    body: {
      detail: "Your session expired or is missing. Sign in again to continue.",
      code: "MISSING_CLIENT_TENANT_SESSION",
    },
  };
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  options: {
    tenantId?: string;
    apiKey?: string;
    accessToken?: string;
    authMode?: RuntimeConfig["authMode"];
    idempotencyKey?: string;
    requireTenant?: boolean;
  } = {},
): Promise<T> {
  const headers = new Headers(init.headers ?? {});
  headers.set("Content-Type", "application/json");

  if (options.requireTenant) {
    const credentials = requireTenantCredentials(options);
    headers.set("X-Tenant-Id", credentials.tenantId);
    if (credentials.authMode === "oidc" && credentials.accessToken) {
      headers.set("Authorization", `Bearer ${credentials.accessToken}`);
    } else if (credentials.apiKey) {
      headers.set("X-Api-Key", credentials.apiKey);
    }
  } else {
    if (options.tenantId?.trim()) {
      headers.set("X-Tenant-Id", options.tenantId.trim());
    }

    if (options.authMode === "oidc" && options.accessToken?.trim()) {
      headers.set("Authorization", `Bearer ${options.accessToken.trim()}`);
    } else if (options.apiKey?.trim()) {
      headers.set("X-Api-Key", options.apiKey.trim());
    }
  }

  if (options.idempotencyKey?.trim()) {
    headers.set("Idempotency-Key", options.idempotencyKey.trim());
  }

  let response: Response;
  try {
    response = await fetch(endpoint(getApiBaseUrl(), path), {
      ...init,
      headers,
    });
  } catch (error) {
    const failure: ApiFailure = {
      status: 0,
      message: "Network error",
      body: {
        detail: "Unable to reach the Ajenda API. Check your connection and try again.",
        code: "NETWORK_ERROR",
        cause: error instanceof Error ? error.message : String(error),
      },
    };
    throw failure;
  }

  const body = await parseBody(response);

  if (!response.ok) {
    const failure: ApiFailure = {
      status: response.status,
      message: `HTTP ${response.status}`,
      body,
    };
    throw failure;
  }

  return body as T;
}

function runtimeOptions(config: RuntimeConfig) {
  return {
    tenantId: config.tenantId,
    apiKey: config.apiKey,
    accessToken: config.accessToken,
    authMode: config.authMode,
    requireTenant: true,
  };
}

async function rotateOidcSession(
  session: CustomerSession,
  reason: "access_expired" | "refresh_failed" | "auth_rejected",
): Promise<CustomerSession> {
  if (!canRefreshSession(session)) {
    forceSignOut({
      reason: session.refreshToken ? "refresh_expired" : "access_expired",
      message: "Your sign-in session expired. Sign in again to continue.",
    });
    throw sessionExpiredFailure("Your sign-in session expired. Sign in again to continue.", reason);
  }

  try {
    const response = await refreshCustomerSession(session.refreshToken!);
    const refreshed = sessionFromOidcResponse(response);
    saveSession(refreshed);
    return refreshed;
  } catch (error) {
    if (isAuthenticationFailure(error)) {
      forceSignOut({
        reason: "refresh_failed",
        message: "Your sign-in session expired. Sign in again to continue.",
      });
      throw sessionExpiredFailure("Your sign-in session expired. Sign in again to continue.", "refresh_failed");
    }
    throw error;
  }
}

export async function ensureFreshSession(session: CustomerSession): Promise<CustomerSession> {
  if (session.authMode !== "oidc") {
    return session;
  }
  if (!shouldRefreshAccessToken(session)) {
    return session;
  }
  return rotateOidcSession(session, "access_expired");
}

async function withFreshSession<T>(
  session: CustomerSession,
  fn: (freshSession: CustomerSession) => Promise<T>,
): Promise<T> {
  const fresh = await ensureFreshSession(session);
  return fn(fresh);
}

type AuthedCaller = CustomerSession | RuntimeConfig;

function isRuntimeConfig(caller: AuthedCaller): caller is RuntimeConfig {
  return "apiBaseUrl" in caller;
}

async function executeAuthedRequest<T>(
  session: CustomerSession,
  fn: (config: RuntimeConfig) => Promise<T>,
  options: { allowRefreshRetry: boolean },
): Promise<T> {
  const run = async (active: CustomerSession) => fn(sessionToRuntimeConfig(active));

  try {
    const fresh = await ensureFreshSession(session);
    return await run(fresh);
  } catch (error) {
    if (!isAuthenticationFailure(error)) {
      throw error;
    }

    if (session.authMode !== "oidc") {
      forceSignOut({
        reason: "auth_rejected",
        message: "Your API key is no longer valid. Sign in again to continue.",
      });
      throw sessionExpiredFailure("Your API key is no longer valid. Sign in again to continue.", "auth_rejected");
    }

    if (!options.allowRefreshRetry) {
      forceSignOut({
        reason: "auth_rejected",
        message: "Your sign-in session expired. Sign in again to continue.",
      });
      throw sessionExpiredFailure("Your sign-in session expired. Sign in again to continue.", "auth_rejected");
    }

    const refreshed = await rotateOidcSession(session, "auth_rejected");
    try {
      return await run(refreshed);
    } catch (retryError) {
      if (isAuthenticationFailure(retryError)) {
        forceSignOut({
          reason: "auth_rejected",
          message: "Your sign-in session expired. Sign in again to continue.",
        });
        throw sessionExpiredFailure("Your sign-in session expired. Sign in again to continue.", "auth_rejected");
      }
      throw retryError;
    }
  }
}

async function withAuthedRuntime<T>(
  caller: AuthedCaller,
  fn: (config: RuntimeConfig) => Promise<T>,
): Promise<T> {
  if (isRuntimeConfig(caller)) {
    return fn(caller);
  }
  return executeAuthedRequest(caller, fn, { allowRefreshRetry: true });
}

export async function getOidcConfig(): Promise<OidcConfigResponse> {
  return request<OidcConfigResponse>("/v1/auth/oidc/config");
}

export async function startOidcLogin(body: {
  redirect_uri: string;
  code_challenge: string;
}): Promise<{ login_intent_id: string; authorization_url: string; expires_at: string }> {
  return request("/v1/auth/oidc/start", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function completeOidcLogin(body: {
  login_intent_id: string;
  code: string;
  code_verifier: string;
  redirect_uri: string;
  tenant_id?: string;
}): Promise<CustomerSessionResponse> {
  return request<CustomerSessionResponse>("/v1/auth/oidc/callback", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function refreshCustomerSession(refreshToken: string): Promise<CustomerSessionResponse> {
  return request<CustomerSessionResponse>("/v1/auth/session/refresh", {
    method: "POST",
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
}

export async function passwordLogin(body: PasswordLoginRequest): Promise<CustomerSessionResponse> {
  return request<CustomerSessionResponse>("/v1/auth/password", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function logoutCustomer(session: CustomerSession): Promise<void> {
  if (session.authMode !== "oidc" || !session.accessToken) {
    return;
  }
  await request(
    "/v1/auth/logout",
    { method: "POST", body: JSON.stringify({}) },
    {
      tenantId: session.tenantId,
      accessToken: session.accessToken,
      authMode: "oidc",
      requireTenant: true,
    },
  );
}

export async function signup(body: SignupRequest): Promise<SignupResponse> {
  return request<SignupResponse>(
    "/v1/onboarding/signup",
    {
      method: "POST",
      body: JSON.stringify(body),
    },
    { idempotencyKey: newIdempotencyKey() },
  );
}

export async function verifyEmail(token: string): Promise<VerifyEmailResponse> {
  return request<VerifyEmailResponse>(
    "/v1/onboarding/verify-email",
    {
      method: "POST",
      body: JSON.stringify({ token }),
    },
    { idempotencyKey: newIdempotencyKey() },
  );
}

export async function resendVerification(email: string): Promise<ResendVerificationResponse> {
  return request<ResendVerificationResponse>(
    "/v1/onboarding/resend-verification",
    {
      method: "POST",
      body: JSON.stringify({ email }),
    },
    { idempotencyKey: newIdempotencyKey() },
  );
}

export async function promoteBootstrapKey(session: CustomerSession): Promise<PromoteBootstrapKeyResponse> {
  return withFreshSession(session, (fresh) =>
    request<PromoteBootstrapKeyResponse>(
      "/v1/onboarding/promote-bootstrap-key",
      { method: "POST", body: JSON.stringify({}) },
      {
        tenantId: fresh.tenantId,
        apiKey: fresh.apiKey,
        accessToken: fresh.accessToken,
        authMode: fresh.authMode,
        idempotencyKey: newIdempotencyKey(),
        requireTenant: true,
      },
    ),
  );
}

export async function getAccountMe(session: CustomerSession): Promise<AccountMeResponse> {
  return withFreshSession(session, (fresh) =>
    request<AccountMeResponse>("/v1/account/me", {}, runtimeOptions(sessionToRuntimeConfig(fresh))),
  );
}

export async function getAccountPlan(session: CustomerSession): Promise<AccountPlanResponse> {
  return withFreshSession(session, (fresh) =>
    request<AccountPlanResponse>("/v1/account/plan", {}, runtimeOptions(sessionToRuntimeConfig(fresh))),
  );
}

export async function getAccountUsage(session: CustomerSession): Promise<AccountUsageResponse> {
  return withFreshSession(session, (fresh) =>
    request<AccountUsageResponse>("/v1/account/usage", {}, runtimeOptions(sessionToRuntimeConfig(fresh))),
  );
}

export async function getAccountBilling(session: CustomerSession): Promise<AccountBillingResponse> {
  return withFreshSession(session, (fresh) =>
    request<AccountBillingResponse>("/v1/account/billing", {}, runtimeOptions(sessionToRuntimeConfig(fresh))),
  );
}

export async function getAccountOnboarding(session: CustomerSession): Promise<AccountOnboardingResponse> {
  return withFreshSession(session, (fresh) =>
    request<AccountOnboardingResponse>("/v1/account/onboarding", {}, runtimeOptions(sessionToRuntimeConfig(fresh))),
  );
}

export async function updateAccountOnboardingPreference(
  session: CustomerSession,
  suppressPrompt: boolean,
): Promise<AccountOnboardingResponse> {
  return withFreshSession(session, (fresh) =>
    request<AccountOnboardingResponse>(
      "/v1/account/onboarding/preferences",
      { method: "PATCH", body: JSON.stringify({ suppress_prompt: suppressPrompt }) },
      runtimeOptions(sessionToRuntimeConfig(fresh)),
    ),
  );
}

export async function completeAccountOnboarding(session: CustomerSession): Promise<AccountOnboardingResponse> {
  return withFreshSession(session, (fresh) =>
    request<AccountOnboardingResponse>(
      "/v1/account/onboarding/complete",
      { method: "POST", body: JSON.stringify({}) },
      runtimeOptions(sessionToRuntimeConfig(fresh)),
    ),
  );
}

export async function listProviderCredentials(
  session: CustomerSession,
): Promise<ProviderCredentialListResponse> {
  return withFreshSession(session, (fresh) =>
    request<ProviderCredentialListResponse>(
      "/v1/account/provider-credentials",
      {},
      runtimeOptions(sessionToRuntimeConfig(fresh)),
    ),
  );
}

export async function createProviderCredential(
  session: CustomerSession,
  body: ProviderCredentialCreateRequest,
): Promise<ProviderCredentialCreateResponse> {
  return withFreshSession(session, (fresh) =>
    request<ProviderCredentialCreateResponse>(
      "/v1/account/provider-credentials",
      { method: "POST", body: JSON.stringify(body) },
      runtimeOptions(sessionToRuntimeConfig(fresh)),
    ),
  );
}

export async function revokeProviderCredential(
  session: CustomerSession,
  credentialId: string,
): Promise<ProviderCredentialResponse> {
  return withFreshSession(session, (fresh) =>
    request<ProviderCredentialResponse>(
      `/v1/account/provider-credentials/${encodeURIComponent(credentialId)}/revoke`,
      { method: "POST", body: JSON.stringify({}) },
      runtimeOptions(sessionToRuntimeConfig(fresh)),
    ),
  );
}

export async function deleteProviderCredential(
  session: CustomerSession,
  credentialId: string,
): Promise<ProviderCredentialResponse> {
  return withFreshSession(session, (fresh) =>
    request<ProviderCredentialResponse>(
      `/v1/account/provider-credentials/${encodeURIComponent(credentialId)}`,
      { method: "DELETE" },
      runtimeOptions(sessionToRuntimeConfig(fresh)),
    ),
  );
}

export async function getGmailOAuthAuthorizeUrl(
  session: CustomerSession,
  credentialId = "gmail-email",
): Promise<GmailOAuthAuthorizeUrlResponse> {
  return withFreshSession(session, (fresh) =>
    request<GmailOAuthAuthorizeUrlResponse>(
      `/v1/account/provider-credentials/gmail/oauth/authorize-url?credential_id=${encodeURIComponent(credentialId)}`,
      { method: "GET" },
      runtimeOptions(sessionToRuntimeConfig(fresh)),
    ),
  );
}

export async function connectGmailOAuth(
  session: CustomerSession,
  body: GmailOAuthConnectRequest,
): Promise<ProviderCredentialCreateResponse> {
  return withFreshSession(session, (fresh) =>
    request<ProviderCredentialCreateResponse>(
      "/v1/account/provider-credentials/gmail/oauth/connect",
      { method: "POST", body: JSON.stringify(body) },
      runtimeOptions(sessionToRuntimeConfig(fresh)),
    ),
  );
}

export async function getLinkedInOAuthAuthorizeUrl(
  session: CustomerSession,
  credentialId = "linkedin-read",
): Promise<GmailOAuthAuthorizeUrlResponse> {
  return withFreshSession(session, (fresh) =>
    request<GmailOAuthAuthorizeUrlResponse>(
      `/v1/account/provider-credentials/linkedin/oauth/authorize-url?credential_id=${encodeURIComponent(credentialId)}`,
      {},
      runtimeOptions(sessionToRuntimeConfig(fresh)),
    ),
  );
}

export async function connectLinkedInOAuth(
  session: CustomerSession,
  body: GmailOAuthConnectRequest,
): Promise<ProviderCredentialCreateResponse> {
  return withFreshSession(session, (fresh) =>
    request<ProviderCredentialCreateResponse>(
      "/v1/account/provider-credentials/linkedin/oauth/connect",
      { method: "POST", body: JSON.stringify(body) },
      runtimeOptions(sessionToRuntimeConfig(fresh)),
    ),
  );
}

export async function getSalesforceOAuthAuthorizeUrl(
  session: CustomerSession,
  credentialId = "salesforce-read",
): Promise<GmailOAuthAuthorizeUrlResponse> {
  return withFreshSession(session, (fresh) =>
    request<GmailOAuthAuthorizeUrlResponse>(
      `/v1/account/provider-credentials/salesforce/oauth/authorize-url?credential_id=${encodeURIComponent(credentialId)}`,
      {},
      runtimeOptions(sessionToRuntimeConfig(fresh)),
    ),
  );
}

export async function connectSalesforceOAuth(
  session: CustomerSession,
  body: GmailOAuthConnectRequest,
): Promise<ProviderCredentialCreateResponse> {
  return withFreshSession(session, (fresh) =>
    request<ProviderCredentialCreateResponse>(
      "/v1/account/provider-credentials/salesforce/oauth/connect",
      { method: "POST", body: JSON.stringify(body) },
      runtimeOptions(sessionToRuntimeConfig(fresh)),
    ),
  );
}

export async function getGoogleCalendarOAuthAuthorizeUrl(
  session: CustomerSession,
  credentialId = "google-calendar-read",
): Promise<GmailOAuthAuthorizeUrlResponse> {
  return withFreshSession(session, (fresh) =>
    request<GmailOAuthAuthorizeUrlResponse>(
      `/v1/account/provider-credentials/google-calendar/oauth/authorize-url?credential_id=${encodeURIComponent(credentialId)}`,
      { method: "GET" },
      runtimeOptions(sessionToRuntimeConfig(fresh)),
    ),
  );
}

export async function connectGoogleCalendarOAuth(
  session: CustomerSession,
  body: GmailOAuthConnectRequest,
): Promise<ProviderCredentialCreateResponse> {
  return withFreshSession(session, (fresh) =>
    request<ProviderCredentialCreateResponse>(
      "/v1/account/provider-credentials/google-calendar/oauth/connect",
      { method: "POST", body: JSON.stringify(body) },
      runtimeOptions(sessionToRuntimeConfig(fresh)),
    ),
  );
}

export async function getGoogleContactsOAuthAuthorizeUrl(
  session: CustomerSession,
  credentialId = "google-contacts-read",
): Promise<GmailOAuthAuthorizeUrlResponse> {
  return withFreshSession(session, (fresh) =>
    request<GmailOAuthAuthorizeUrlResponse>(
      `/v1/account/provider-credentials/google-contacts/oauth/authorize-url?credential_id=${encodeURIComponent(credentialId)}`,
      { method: "GET" },
      runtimeOptions(sessionToRuntimeConfig(fresh)),
    ),
  );
}

export async function connectGoogleContactsOAuth(
  session: CustomerSession,
  body: GmailOAuthConnectRequest,
): Promise<ProviderCredentialCreateResponse> {
  return withFreshSession(session, (fresh) =>
    request<ProviderCredentialCreateResponse>(
      "/v1/account/provider-credentials/google-contacts/oauth/connect",
      { method: "POST", body: JSON.stringify(body) },
      runtimeOptions(sessionToRuntimeConfig(fresh)),
    ),
  );
}

export async function getGoogleDocsOAuthAuthorizeUrl(
  session: CustomerSession,
  credentialId = "google-docs",
): Promise<GmailOAuthAuthorizeUrlResponse> {
  return withFreshSession(session, (fresh) =>
    request<GmailOAuthAuthorizeUrlResponse>(
      `/v1/account/provider-credentials/google-docs/oauth/authorize-url?credential_id=${encodeURIComponent(credentialId)}`,
      { method: "GET" },
      runtimeOptions(sessionToRuntimeConfig(fresh)),
    ),
  );
}

export async function connectGoogleDocsOAuth(
  session: CustomerSession,
  body: GmailOAuthConnectRequest,
): Promise<ProviderCredentialCreateResponse> {
  return withFreshSession(session, (fresh) =>
    request<ProviderCredentialCreateResponse>(
      "/v1/account/provider-credentials/google-docs/oauth/connect",
      { method: "POST", body: JSON.stringify(body) },
      runtimeOptions(sessionToRuntimeConfig(fresh)),
    ),
  );
}

export async function getGitHubOAuthAuthorizeUrl(
  session: CustomerSession,
  credentialId = "github-read",
): Promise<GmailOAuthAuthorizeUrlResponse> {
  return withFreshSession(session, (fresh) =>
    request<GmailOAuthAuthorizeUrlResponse>(
      `/v1/account/provider-credentials/github/oauth/authorize-url?credential_id=${encodeURIComponent(credentialId)}`,
      {},
      runtimeOptions(sessionToRuntimeConfig(fresh)),
    ),
  );
}

export async function connectGitHubOAuth(
  session: CustomerSession,
  body: GmailOAuthConnectRequest,
): Promise<ProviderCredentialCreateResponse> {
  return withFreshSession(session, (fresh) =>
    request<ProviderCredentialCreateResponse>(
      "/v1/account/provider-credentials/github/oauth/connect",
      { method: "POST", body: JSON.stringify(body) },
      runtimeOptions(sessionToRuntimeConfig(fresh)),
    ),
  );
}

export async function listMissions(
  caller: AuthedCaller,
  options?: { limit?: number },
): Promise<MissionListResponse> {
  const limit = options?.limit ?? 50;
  return withAuthedRuntime(caller, (config) =>
    request<MissionListResponse>(`/v1/missions?limit=${limit}`, {}, runtimeOptions(config)),
  );
}

export async function createMission(
  caller: AuthedCaller,
  body: MissionCreateRequest,
): Promise<MissionReadResponse> {
  return withAuthedRuntime(caller, (config) =>
    request<MissionReadResponse>(
      "/v1/missions",
      {
        method: "POST",
        body: JSON.stringify({
          compliance_category: "operational",
          jurisdiction: "US-ALL",
          ...body,
        }),
      },
      runtimeOptions(config),
    ),
  );
}

export async function composeMission(
  caller: AuthedCaller,
  body: { instruction: string; interpretation_thread_id?: string },
): Promise<MissionComposeResponse> {
  return withAuthedRuntime(caller, (config) =>
    request<MissionComposeResponse>(
      "/v1/missions/compose",
      { method: "POST", body: JSON.stringify(body) },
      runtimeOptions(config),
    ),
  );
}

export async function confirmMissionComposition(
  caller: AuthedCaller,
  proposalId: string,
  body?: { composition?: Record<string, unknown>; idempotency_key?: string },
): Promise<MissionComposeConfirmResponse> {
  return withAuthedRuntime(caller, (config) => {
    const idempotencyKey = body?.idempotency_key?.trim() || newIdempotencyKey();
    const payload = {
      ...(body ?? {}),
      idempotency_key: idempotencyKey,
    };
    return request<MissionComposeConfirmResponse>(
      `/v1/missions/proposals/${encodeURIComponent(proposalId)}/confirm`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
      { ...runtimeOptions(config), idempotencyKey },
    );
  });
}

export async function getMission(caller: AuthedCaller, missionId: string): Promise<MissionReadResponse> {
  return withAuthedRuntime(caller, (config) =>
    request<MissionReadResponse>(
      `/v1/missions/${encodeURIComponent(missionId)}`,
      {},
      runtimeOptions(config),
    ),
  );
}

export async function getMissionLifecycle(
  caller: AuthedCaller,
  missionId: string,
): Promise<MissionLifecycleReadResponse> {
  return withAuthedRuntime(caller, (config) =>
    request<MissionLifecycleReadResponse>(
      `/v1/missions/${encodeURIComponent(missionId)}/lifecycle`,
      {},
      runtimeOptions(config),
    ),
  );
}

export async function createMissionPlan(
  caller: AuthedCaller,
  missionId: string,
  body: MissionPlanCreateRequest,
): Promise<MissionPlanReadResponse> {
  return withAuthedRuntime(caller, (config) =>
    request<MissionPlanReadResponse>(
      `/v1/missions/${encodeURIComponent(missionId)}/plan`,
      { method: "POST", body: JSON.stringify(body) },
      runtimeOptions(config),
    ),
  );
}

export async function upsertMissionTaskGraph(
  caller: AuthedCaller,
  missionId: string,
  body: MissionTaskGraphPayload,
): Promise<MissionTaskGraphReadResponse> {
  return withAuthedRuntime(caller, (config) =>
    request<MissionTaskGraphReadResponse>(
      `/v1/missions/${encodeURIComponent(missionId)}/task-graph`,
      { method: "PUT", body: JSON.stringify(body) },
      runtimeOptions(config),
    ),
  );
}

/** Server-owned mission compile — replaces client graph compilers. */
export async function compileMission(
  caller: AuthedCaller,
  missionId: string,
  body?: { instruction?: string; persist?: boolean; source?: string },
): Promise<Record<string, unknown>> {
  return withAuthedRuntime(caller, (config) =>
    request<Record<string, unknown>>(
      `/v1/missions/${encodeURIComponent(missionId)}/compile`,
      {
        method: "POST",
        body: JSON.stringify({
          persist: true,
          source: "mission_dispatch_ui",
          ...body,
        }),
      },
      runtimeOptions(config),
    ),
  );
}

export async function materializeMissionGraph(
  caller: AuthedCaller,
  missionId: string,
  body: GraphMaterializationWriteRequest,
): Promise<GraphMaterializationReadResponse> {
  return withAuthedRuntime(caller, (config) =>
    request<GraphMaterializationReadResponse>(
      `/v1/missions/${encodeURIComponent(missionId)}/materialize-graph`,
      { method: "POST", body: JSON.stringify(body) },
      runtimeOptions(config),
    ),
  );
}

export async function provisionBridgeRuntimeAuthority(
  caller: AuthedCaller,
  missionId: string,
): Promise<BridgeRuntimeAuthorityReadResponse> {
  return withAuthedRuntime(caller, (config) =>
    request<BridgeRuntimeAuthorityReadResponse>(
      `/v1/missions/${encodeURIComponent(missionId)}/bridge-runtime-authority`,
      { method: "POST", body: JSON.stringify({}) },
      runtimeOptions(config),
    ),
  );
}

/** Server-owned runtime admission — empty body derives nodes from compiled graph. */
export async function admitMissionToRuntime(
  caller: AuthedCaller,
  missionId: string,
  body: RuntimeAdmissionWriteRequest = {},
): Promise<RuntimeAdmissionReadResponse> {
  return withAuthedRuntime(caller, (config) =>
    request<RuntimeAdmissionReadResponse>(
      `/v1/missions/${encodeURIComponent(missionId)}/runtime-admission`,
      {
        method: "POST",
        body: JSON.stringify({
          admission_status: "admitted",
          auto_provision_authority: true,
          selected_nodes: [],
          ...body,
        }),
      },
      runtimeOptions(config),
    ),
  );
}

export async function getMissionRuntimeReadiness(
  caller: AuthedCaller,
  missionId: string,
): Promise<RuntimeReadinessReadResponse> {
  return withAuthedRuntime(caller, (config) =>
    request<RuntimeReadinessReadResponse>(
      `/v1/missions/${encodeURIComponent(missionId)}/runtime-readiness`,
      {},
      runtimeOptions(config),
    ),
  );
}

export async function materializeMissionRuntimeTasks(
  caller: AuthedCaller,
  missionId: string,
): Promise<RuntimeTaskMaterializationReadResponse> {
  return withAuthedRuntime(caller, (config) =>
    request<RuntimeTaskMaterializationReadResponse>(
      `/v1/missions/${encodeURIComponent(missionId)}/runtime-task-materialization`,
      { method: "POST", body: JSON.stringify({}) },
      runtimeOptions(config),
    ),
  );
}

export async function admitMissionRuntimeQueue(
  caller: AuthedCaller,
  missionId: string,
): Promise<RuntimeQueueAdmissionResponse> {
  return withAuthedRuntime(caller, (config) =>
    request<RuntimeQueueAdmissionResponse>(
      `/v1/missions/${encodeURIComponent(missionId)}/runtime-queue-admission`,
      { method: "POST", body: JSON.stringify({}) },
      runtimeOptions(config),
    ),
  );
}

export async function getMissionDispatchReadiness(
  caller: AuthedCaller,
  missionId: string,
): Promise<RuntimeDispatchReadinessReadResponse> {
  return withAuthedRuntime(caller, (config) =>
    request<RuntimeDispatchReadinessReadResponse>(
      `/v1/missions/${encodeURIComponent(missionId)}/runtime-dispatch-readiness`,
      {},
      runtimeOptions(config),
    ),
  );
}

export async function listActions(caller: AuthedCaller): Promise<AbilityActionListResponse> {
  return withAuthedRuntime(caller, (config) =>
    request<AbilityActionListResponse>("/v1/ability-runtime/actions", {}, runtimeOptions(config)),
  );
}

export async function listAutonomyDisclaimers(
  caller: AuthedCaller,
): Promise<AutonomyDisclaimerListResponse> {
  return withAuthedRuntime(caller, (config) =>
    request<AutonomyDisclaimerListResponse>(
      "/v1/ability-runtime/disclaimers",
      {},
      runtimeOptions(config),
    ),
  );
}

export async function getBrainCapabilityCheck(
  caller: AuthedCaller,
): Promise<BrainCapabilityCheckResponse> {
  return withAuthedRuntime(caller, (config) =>
    request<BrainCapabilityCheckResponse>(
      "/v1/ability-runtime/brain-capability-check",
      {},
      runtimeOptions(config),
    ),
  );
}

export async function listBrainMissions(caller: AuthedCaller): Promise<BrainMissionListResponse> {
  return withAuthedRuntime(caller, (config) =>
    request<BrainMissionListResponse>("/v1/ability-runtime/brain-missions", {}, runtimeOptions(config)),
  );
}

export async function listReviewQueue(
  caller: AuthedCaller,
  options?: { status?: "pending" | "approved" | "rejected" | "sent"; limit?: number },
): Promise<ReviewQueueListResponse> {
  const params = new URLSearchParams();
  if (options?.status) {
    params.set("status", options.status);
  }
  if (options?.limit) {
    params.set("limit", String(options.limit));
  }
  const query = params.toString();
  return withAuthedRuntime(caller, (config) =>
    request<ReviewQueueListResponse>(
      `/v1/review-queue${query ? `?${query}` : ""}`,
      {},
      runtimeOptions(config),
    ),
  );
}

export async function listPendingTaskApprovals(caller: AuthedCaller): Promise<ReviewQueueListResponse> {
  return withAuthedRuntime(caller, (config) =>
    request<ReviewQueueListResponse>("/v1/review-queue/tasks?limit=50", {}, runtimeOptions(config)),
  );
}

export async function approveTaskReview(
  caller: AuthedCaller,
  taskId: string,
): Promise<{ task_id: string; status: string }> {
  return withAuthedRuntime(caller, (config) =>
    request<{ task_id: string; status: string }>(
      `/v1/review-queue/tasks/${encodeURIComponent(taskId)}/approve`,
      {
        method: "POST",
        body: JSON.stringify({ approval_expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString() }),
      },
      runtimeOptions(config),
    ),
  );
}

export async function approveReviewQueueItem(
  caller: AuthedCaller,
  artifactId: string,
  note?: string,
): Promise<ReviewQueueItem> {
  return withAuthedRuntime(caller, (config) =>
    request<ReviewQueueItem>(
      `/v1/review-queue/${encodeURIComponent(artifactId)}/approve`,
      {
        method: "POST",
        body: JSON.stringify({ note: note ?? null }),
      },
      runtimeOptions(config),
    ),
  );
}

export async function launchTask(
  caller: AuthedCaller,
  body: AbilityTaskCreate,
  options?: { idempotencyKey?: string },
): Promise<AbilityTaskQueuedResponse> {
  const idempotencyKey = options?.idempotencyKey ?? body.idempotency_key ?? newIdempotencyKey();
  return withAuthedRuntime(caller, (config) =>
    request<AbilityTaskQueuedResponse>(
      "/v1/ability-runtime/tasks",
      {
        method: "POST",
        body: JSON.stringify({ ...body, idempotency_key: body.idempotency_key ?? idempotencyKey }),
      },
      { ...runtimeOptions(config), idempotencyKey },
    ),
  );
}

export async function launchProof(
  caller: AuthedCaller,
  proof: "calendar-read" | "calendar-create" | "sales-qualify" | "sales-draft-followup",
): Promise<AbilityTaskQueuedResponse> {
  return withAuthedRuntime(caller, (config) =>
    request<AbilityTaskQueuedResponse>(
      `/v1/ability-runtime/proofs/${proof}`,
      {
        method: "POST",
        body: JSON.stringify({}),
      },
      runtimeOptions(config),
    ),
  );
}

export async function getTaskStatus(
  caller: AuthedCaller,
  taskId: string,
): Promise<AbilityTaskStatusResponse> {
  return withAuthedRuntime(caller, (config) =>
    request<AbilityTaskStatusResponse>(
      `/v1/ability-runtime/tasks/${taskId}`,
      {},
      runtimeOptions(config),
    ),
  );
}

export async function cancelTask(
  caller: AuthedCaller,
  taskId: string,
  reason = "Stopped by operator",
): Promise<{ task_id: string; mission_id: string; status: string; cancellation_requested: boolean }> {
  return withAuthedRuntime(caller, (config) =>
    request(`/v1/tasks/${encodeURIComponent(taskId)}/cancel`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }, runtimeOptions(config)),
  );
}

export async function cancelMission(
  caller: AuthedCaller,
  missionId: string,
  reason = "Stopped by operator",
): Promise<{ mission_id: string; status: string; cancelled_tasks: number; cancellation_requested_tasks: number }> {
  return withAuthedRuntime(caller, (config) =>
    request(`/v1/missions/${encodeURIComponent(missionId)}/cancel`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }, runtimeOptions(config)),
  );
}

export async function createCheckout(
  caller: AuthedCaller,
  plan: "starter" | "pro",
): Promise<CheckoutResponse> {
  return withAuthedRuntime(caller, (config) =>
    request<CheckoutResponse>(
      "/v1/billing/checkout",
      {
        method: "POST",
        body: JSON.stringify({
          plan,
          success_url: `${window.location.origin}/billing/success`,
          cancel_url: `${window.location.origin}/billing/cancel`,
        }),
      },
      runtimeOptions(config),
    ),
  );
}

export async function createPortal(caller: AuthedCaller): Promise<PortalResponse> {
  const returnUrl = encodeURIComponent(`${window.location.origin}/billing`);
  return withAuthedRuntime(caller, (config) =>
    request<PortalResponse>(
      `/v1/billing/portal?return_url=${returnUrl}`,
      { method: "GET" },
      runtimeOptions(config),
    ),
  );
}

export async function getBusinessProfile(caller: AuthedCaller): Promise<BusinessProfileReadResponse> {
  return withAuthedRuntime(caller, (config) =>
    request<BusinessProfileReadResponse>("/v1/business-profile", {}, runtimeOptions(config)),
  );
}

export async function upsertBusinessProfileFact(
  caller: AuthedCaller,
  category: string,
  body: BusinessProfileFactUpsertRequest,
): Promise<BusinessProfileReadResponse> {
  return withAuthedRuntime(caller, (config) =>
    request<BusinessProfileReadResponse>(
      `/v1/business-profile/facts/${encodeURIComponent(category)}`,
      { method: "PUT", body: JSON.stringify(body) },
      runtimeOptions(config),
    ),
  );
}

export async function listCrmRecords(
  caller: AuthedCaller,
  options: {
    recordType: "account" | "contact" | "opportunity" | "activity" | "task" | "document";
    query?: string;
    stage?: string;
    accountId?: string;
    limit?: number;
    offset?: number;
  },
): Promise<CrmRecordListResponse> {
  const params = new URLSearchParams({ record_type: options.recordType });
  if (options.query) {
    params.set("query", options.query);
  }
  if (options.stage) {
    params.set("stage", options.stage);
  }
  if (options.accountId) {
    params.set("account_id", options.accountId);
  }
  if (options.limit) {
    params.set("limit", String(options.limit));
  }
  if (options.offset) {
    params.set("offset", String(options.offset));
  }
  return withAuthedRuntime(caller, (config) =>
    request<CrmRecordListResponse>(`/v1/crm/records?${params}`, {}, runtimeOptions(config)),
  );
}

export async function getCrmRecord(
  caller: AuthedCaller,
  recordType: string,
  recordId: string,
): Promise<CrmRecordItem> {
  return withAuthedRuntime(caller, (config) =>
    request<CrmRecordItem>(
      `/v1/crm/records/${encodeURIComponent(recordType)}/${encodeURIComponent(recordId)}`,
      {},
      runtimeOptions(config),
    ),
  );
}

export async function upsertCrmRecord(
  caller: AuthedCaller,
  recordType: string,
  recordId: string,
  data: CrmRecordWriteRequest,
): Promise<CrmRecordItem> {
  return withAuthedRuntime(caller, (config) =>
    request<CrmRecordItem>(
      `/v1/crm/records/${encodeURIComponent(recordType)}/${encodeURIComponent(recordId)}`,
      { method: "PUT", body: JSON.stringify(data) },
      runtimeOptions(config),
    ),
  );
}

export async function getCrmTimeline(
  caller: AuthedCaller,
  recordType: string,
  recordId: string,
): Promise<CrmTimelineResponse> {
  return withAuthedRuntime(caller, (config) =>
    request<CrmTimelineResponse>(
      `/v1/crm/records/${encodeURIComponent(recordType)}/${encodeURIComponent(recordId)}/timeline`,
      {},
      runtimeOptions(config),
    ),
  );
}

export async function getCrmRelationships(
  caller: AuthedCaller,
  recordType: string,
  recordId: string,
): Promise<CrmRelationshipResponse> {
  const params = new URLSearchParams({ record_type: recordType, record_id: recordId });
  return withAuthedRuntime(caller, (config) =>
    request<CrmRelationshipResponse>(`/v1/crm/relationships?${params.toString()}`, {}, runtimeOptions(config)),
  );
}

export async function getCrmPipeline(caller: AuthedCaller): Promise<CrmPipelineResponse> {
  return withAuthedRuntime(caller, (config) =>
    request<CrmPipelineResponse>("/v1/crm/pipeline", {}, runtimeOptions(config)),
  );
}

export async function listCrmSuggestions(caller: AuthedCaller): Promise<CrmSuggestionsResponse> {
  return withAuthedRuntime(caller, (config) =>
    request<CrmSuggestionsResponse>("/v1/crm/suggestions", {}, runtimeOptions(config)),
  );
}
