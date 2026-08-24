import { getApiBaseUrl } from "../auth/session";
import type { ApiFailure } from "../types";
import { newIdempotencyKey } from "../utils/errors";

export interface SignupRequest {
  org_name: string;
  email: string;
  slug?: string;
  password: string;
}

export interface SignupResponse {
  email: string;
  status: "verification_required";
  verification_code?: string | null;
}

export interface ResendVerificationResponse {
  email: string;
  status: "verification_if_pending";
  verification_code?: string | null;
}

export interface VerifyEmailResponse {
  tenant_id: string;
  key_id: string;
  api_key: string;
  bootstrap_expires_at: string;
}

function endpoint(path: string): string {
  const base = getApiBaseUrl().trim().replace(/\/+$/, "");
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${base}${normalized}`;
}

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

async function publicRequest<T>(path: string, body: unknown, *, idempotent = false): Promise<T> {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (idempotent) {
    headers.set("Idempotency-Key", newIdempotencyKey());
  }

  let response: Response;
  try {
    response = await fetch(endpoint(path), {
      method: "POST",
      headers,
      body: JSON.stringify(body),
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

  const responseBody = await parseBody(response);
  if (!response.ok) {
    const failure: ApiFailure = {
      status: response.status,
      message: `HTTP ${response.status}`,
      body: responseBody,
    };
    throw failure;
  }
  return responseBody as T;
}

export async function signup(body: SignupRequest): Promise<SignupResponse> {
  return publicRequest<SignupResponse>("/v1/onboarding/signup", body, { idempotent: true });
}

export async function verifyEmail(email: string, code: string): Promise<VerifyEmailResponse> {
  return publicRequest<VerifyEmailResponse>(
    "/v1/onboarding/verify-email",
    { email, code },
    { idempotent: true },
  );
}

export async function resendVerification(email: string): Promise<ResendVerificationResponse> {
  return publicRequest<ResendVerificationResponse>("/v1/onboarding/resend-verification", { email });
}
