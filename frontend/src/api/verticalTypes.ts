import type { VerticalTemplateCreateMissionRequest } from "../types";

export interface VerticalPlanRequest extends VerticalTemplateCreateMissionRequest {
  step_inputs?: Record<string, Record<string, unknown>>;
  idempotency_keys?: Record<string, string>;
  credential_references?: Record<string, {
    schema_version: 1;
    credential_id: string;
    provider: string;
    credential_type: string;
  }>;
}
