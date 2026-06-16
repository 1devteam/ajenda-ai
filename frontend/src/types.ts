export type ProviderMode = "local" | "external" | "mixed";

export interface RuntimeConfig {
  apiBaseUrl: string;
  tenantId: string;
  apiKey: string;
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
