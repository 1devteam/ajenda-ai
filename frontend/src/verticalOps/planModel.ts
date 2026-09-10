import type { ProviderCredentialResponse, VerticalTemplate } from "../types";
import type { VerticalPlanRequest } from "../api/verticalTypes";

export function socialConnections(credentials: ProviderCredentialResponse[], tenantId: string) {
  return credentials.filter((item) =>
    item.tenant_id === tenantId && item.enabled && !item.revoked &&
    item.provider === "external_social" && item.credential_type === "api_key" &&
    (!item.allowed_actions.length || item.allowed_actions.includes("gtm.social_publish")) &&
    (!item.allowed_side_effect_classes.length || item.allowed_side_effect_classes.includes("external_publish")),
  );
}

export interface PlanFields {
  query: string;
  content: string;
  platform: string;
  credentialId: string;
}

export function buildVerticalPlan(
  template: VerticalTemplate,
  fields: PlanFields,
  credentials: ProviderCredentialResponse[],
  tenantId: string,
  operationKey: string,
): VerticalPlanRequest {
  const steps = template.steps.filter((step) => step.include_by_default);
  if (!steps.length) throw new Error("This template has no default steps to plan.");
  const request: VerticalPlanRequest = {
    template_id: template.template_id,
    mission_objective: template.objective_template,
    selected_step_keys: steps.map((step) => step.step_key),
    queue: false,
    step_inputs: {},
  };
  for (const step of steps) {
    if (!template.allows_runtime_queue) continue;
    if (step.action_name === "web.research") {
      if (!fields.query.trim() || fields.query.length > 500) {
        throw new Error("Enter a research question of up to 500 characters.");
      }
      request.step_inputs![step.step_key] = { query: fields.query.trim() };
      request.mission_objective = fields.query.trim();
    } else if (step.action_name === "gtm.social_publish") {
      if (!fields.content.trim() || fields.content.length > 280) {
        throw new Error("Enter post content of up to 280 characters.");
      }
      if (!fields.platform.trim() || fields.platform.length > 80) {
        throw new Error("Enter the connection’s platform (up to 80 characters).");
      }
      const credential = socialConnections(credentials, tenantId)
        .find((item) => item.credential_id === fields.credentialId);
      if (!credential) throw new Error("Choose an available social publishing connection.");
      request.step_inputs![step.step_key] = { platform: fields.platform.trim(), content: fields.content };
      request.idempotency_keys = { [step.step_key]: operationKey };
      request.credential_references = { [step.step_key]: {
        schema_version: 1,
        credential_id: credential.credential_id,
        provider: credential.provider,
        credential_type: credential.credential_type,
      } };
    } else if (!["gtm.email_draft", "vertical.finance.sync_revenue"].includes(step.action_name)) {
      throw new Error("This template needs inputs that this page does not yet support.");
    }
  }
  return request;
}
