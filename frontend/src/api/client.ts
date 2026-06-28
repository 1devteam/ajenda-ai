import {
  getApiBaseUrl,
  isSessionNearExpiry,
  saveSession,
  sessionFromOidcResponse,
  sessionToRuntimeConfig,
} from "../auth/session";
import { newIdempotencyKey } from "../utils/errors";
import type {
  AbilityActionListResponse,
  AutonomyDisclaimerListResponse,
  AbilityTaskCreate,
  AbilityTaskQueuedResponse,
  AbilityTaskStatusResponse,
  MissionCreateRequest,
  MissionListResponse,
  MissionReadResponse,
  AccountBillingResponse,
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
  PortalResponse,
  PromoteBootstrapKeyResponse,
  RuntimeConfig,
  ResendVerificationResponse,
  SignupRequest,
  SignupResponse,
  VerifyEmailResponse,
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

  const response = await fetch(endpoint(getApiBaseUrl(), path), {
    ...init,
    headers,
  });

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

export async function ensureFreshSession(session: CustomerSession): Promise<CustomerSession> {
  if (session.authMode !== "oidc" || !session.refreshToken || !isSessionNearExpiry(session)) {
    return session;
  }

  const response = await refreshCustomerSession(session.refreshToken);
  const refreshed = sessionFromOidcResponse(response);
  saveSession(refreshed);
  return refreshed;
}

async function withFreshSession<T>(
  session: CustomerSession,
  fn: (freshSession: CustomerSession) => Promise<T>,
): Promise<T> {
  const fresh = await ensureFreshSession(session);
  return fn(fresh);
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
      {},
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
      {},
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

function authedRuntimeOptions(config: RuntimeConfig) {
  return runtimeOptions(config);
}

export async function listMissions(
  config: RuntimeConfig,
  options?: { limit?: number },
): Promise<MissionListResponse> {
  const limit = options?.limit ?? 50;
  return request<MissionListResponse>(`/v1/missions?limit=${limit}`, {}, authedRuntimeOptions(config));
}

export async function createMission(
  config: RuntimeConfig,
  body: MissionCreateRequest,
): Promise<MissionReadResponse> {
  return request<MissionReadResponse>(
    "/v1/missions",
    {
      method: "POST",
      body: JSON.stringify({
        compliance_category: "operational",
        jurisdiction: "US-ALL",
        ...body,
      }),
    },
    authedRuntimeOptions(config),
  );
}

export async function listActions(config: RuntimeConfig): Promise<AbilityActionListResponse> {
  return request<AbilityActionListResponse>("/v1/ability-runtime/actions", {}, authedRuntimeOptions(config));
}

export async function listAutonomyDisclaimers(
  config: RuntimeConfig,
): Promise<AutonomyDisclaimerListResponse> {
  return request<AutonomyDisclaimerListResponse>(
    "/v1/ability-runtime/disclaimers",
    {},
    authedRuntimeOptions(config),
  );
}

export async function launchTask(
  config: RuntimeConfig,
  body: AbilityTaskCreate,
  options?: { idempotencyKey?: string },
): Promise<AbilityTaskQueuedResponse> {
  const idempotencyKey = options?.idempotencyKey ?? body.idempotency_key ?? newIdempotencyKey();
  return request<AbilityTaskQueuedResponse>(
    "/v1/ability-runtime/tasks",
    {
      method: "POST",
      body: JSON.stringify({ ...body, idempotency_key: body.idempotency_key ?? idempotencyKey }),
    },
    { ...authedRuntimeOptions(config), idempotencyKey },
  );
}

export async function launchProof(
  config: RuntimeConfig,
  proof: "calendar-read" | "calendar-create" | "sales-qualify" | "sales-draft-followup",
): Promise<AbilityTaskQueuedResponse> {
  return request<AbilityTaskQueuedResponse>(
    `/v1/ability-runtime/proofs/${proof}`,
    {
      method: "POST",
      body: JSON.stringify({}),
    },
    authedRuntimeOptions(config),
  );
}

export async function getTaskStatus(
  config: RuntimeConfig,
  taskId: string,
): Promise<AbilityTaskStatusResponse> {
  return request<AbilityTaskStatusResponse>(
    `/v1/ability-runtime/tasks/${taskId}`,
    {},
    authedRuntimeOptions(config),
  );
}

export async function createCheckout(
  config: RuntimeConfig,
  plan: "starter" | "pro",
): Promise<CheckoutResponse> {
  return request<CheckoutResponse>(
    "/v1/billing/checkout",
    {
      method: "POST",
      body: JSON.stringify({
        plan,
        success_url: `${window.location.origin}/billing/success`,
        cancel_url: `${window.location.origin}/billing/cancel`,
      }),
    },
    authedRuntimeOptions(config),
  );
}

export async function createPortal(config: RuntimeConfig): Promise<PortalResponse> {
  const returnUrl = encodeURIComponent(`${window.location.origin}/billing`);
  return request<PortalResponse>(
    `/v1/billing/portal?return_url=${returnUrl}`,
    { method: "GET" },
    authedRuntimeOptions(config),
  );
}