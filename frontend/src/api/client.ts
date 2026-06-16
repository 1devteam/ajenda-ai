import type {
  AbilityActionListResponse,
  AbilityTaskCreate,
  AbilityTaskQueuedResponse,
  AbilityTaskStatusResponse,
  ApiFailure,
  CheckoutResponse,
  PortalResponse,
  RuntimeConfig,
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

function endpoint(config: RuntimeConfig, path: string): string {
  const base = config.apiBaseUrl.trim().replace(/\/+$/, "");
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${base}${normalized}`;
}

async function request<T>(
  config: RuntimeConfig,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers ?? {});
  headers.set("Content-Type", "application/json");

  if (config.tenantId.trim()) {
    headers.set("X-Tenant-Id", config.tenantId.trim());
  }

  if (config.apiKey.trim()) {
    headers.set("X-Api-Key", config.apiKey.trim());
  }

  const response = await fetch(endpoint(config, path), {
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

export async function listActions(config: RuntimeConfig): Promise<AbilityActionListResponse> {
  return request<AbilityActionListResponse>(config, "/v1/ability-runtime/actions");
}

export async function launchTask(
  config: RuntimeConfig,
  body: AbilityTaskCreate,
): Promise<AbilityTaskQueuedResponse> {
  return request<AbilityTaskQueuedResponse>(config, "/v1/ability-runtime/tasks", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function launchProof(
  config: RuntimeConfig,
  proof: "calendar-read" | "calendar-create" | "sales-qualify" | "sales-draft-followup",
): Promise<AbilityTaskQueuedResponse> {
  return request<AbilityTaskQueuedResponse>(config, `/v1/ability-runtime/proofs/${proof}`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function getTaskStatus(
  config: RuntimeConfig,
  taskId: string,
): Promise<AbilityTaskStatusResponse> {
  return request<AbilityTaskStatusResponse>(config, `/v1/ability-runtime/tasks/${taskId}`);
}

export async function createCheckout(
  config: RuntimeConfig,
  plan: "starter" | "pro",
): Promise<CheckoutResponse> {
  return request<CheckoutResponse>(config, "/v1/billing/checkout", {
    method: "POST",
    body: JSON.stringify({
      plan,
      success_url: `${window.location.origin}/billing/success`,
      cancel_url: `${window.location.origin}/billing/cancel`,
    }),
  });
}

export async function createPortal(config: RuntimeConfig): Promise<PortalResponse> {
  const returnUrl = encodeURIComponent(`${window.location.origin}/billing`);
  return request<PortalResponse>(config, `/v1/billing/portal?return_url=${returnUrl}`, {
    method: "GET",
  });
}
