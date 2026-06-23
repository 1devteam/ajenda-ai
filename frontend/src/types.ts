export type ProviderMode = "local" | "external" | "mixed";

export type SessionPhase = "bootstrap" | "operational";
export type AuthMode = "oidc" | "api_key";

export interface RuntimeConfig {
  apiBaseUrl: string;
  tenantId: string;
  apiKey: string;
  accessToken?: string;
  authMode?: AuthMode;
}

export interface CustomerSession {
  authMode: AuthMode;
  tenantId: string;
  phase: SessionPhase;
  apiKey?: string;
  keyId?: string;
  accessToken?: string;
  refreshToken?: string;
  expiresAt?: string;
  email?: string;
  orgName?: string;
  slug?: string;
  plan?: string;
}

export interface OidcConfigResponse {
  enabled: boolean;
  provider: string;
  client_id: string | null;
  authorization_endpoint: string | null;
  scopes: string;
}

export interface OidcTenantChoice {
  tenant_id: string;
  org_name: string;
  slug: string;
}

export interface CustomerSessionResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  refresh_expires_in: number;
  tenant_id: string;
  email: string;
  org_name: string;
  slug: string;
  plan: string;
}

export interface SignupRequest {
  org_name: string;
  email: string;
  slug?: string;
}

export interface SignupResponse {
  tenant_id: string;
  slug: string;
  plan: string;
  email: string;
  status: string;
  verification_expires_at: string;
  verification_token?: string | null;
}

export interface ResendVerificationResponse {
  tenant_id: string;
  email: string;
  status: string;
  verification_expires_at: string;
  verification_token?: string | null;
}

export interface VerifyEmailResponse {
  tenant_id: string;
  key_id: string;
  api_key: string;
  bootstrap_expires_at: string;
}

export interface PromoteBootstrapKeyResponse {
  tenant_id: string;
  key_id: string;
  api_key: string;
  revoked_bootstrap_key_id: string;
}

export interface AccountMeResponse {
  tenant: {
    tenant_id: string;
    name: string;
    slug: string;
    status: string;
    plan: string;
    created_at: string;
  };
  principal: {
    subject_id: string;
    principal_type: string;
    roles: string[];
    email?: string | null;
  };
  membership?: {
    email: string;
    role: string;
    status: string;
  } | null;
}

export interface AccountPlanResponse {
  slug: string;
  display_name: string;
  limits: Record<string, number>;
  features_enabled: string[];
}

export interface AccountUsageResponse {
  tenant_id: string;
  plan: string;
  billing_period: string;
  usage: Record<string, number>;
  limits: Record<string, number>;
}

export interface AccountBillingResponse {
  tenant_id: string;
  plan: string;
  tenant_status: string;
  has_billing_account: boolean;
  stripe_customer_id?: string | null;
}

export interface AbilityAction {
  name: string;
  provider: string;
  side_effect_class: string;
  enabled: boolean;
  label: string;
  requires_authority: boolean;
  provider_mode: ProviderMode;
}

export interface AbilityActionListResponse {
  actions: AbilityAction[];
}

export interface AbilityTaskCreate {
  action: string;
  input: Record<string, unknown>;
  title?: string;
  description?: string;
  mission_objective?: string;
  idempotency_key?: string;
  approved_by?: string;
  approval_reason?: string;
}

export interface AbilityTaskQueuedResponse {
  task_id: string;
  mission_id: string;
  status: string;
  action: string;
  queue_status: string;
  queue_reason?: string | null;
}

export interface AbilityTaskStatusResponse {
  task_id: string;
  mission_id: string | null;
  title: string;
  description: string | null;
  status: string;
  action: string | null;
  metadata_json: Record<string, unknown>;
  lineage: Array<Record<string, unknown>>;
  evidence: Array<Record<string, unknown>>;
  audit: Array<Record<string, unknown>>;
}

export interface CheckoutResponse {
  checkout_url: string;
}

export interface PortalResponse {
  portal_url: string;
}

export interface ApiFailure {
  status: number;
  message: string;
  body: unknown;
}