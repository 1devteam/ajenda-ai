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
  refreshExpiresAt?: string;
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

export interface PasswordLoginRequest {
  email: string;
  password: string;
  tenant_id?: string;
}

export interface SignupRequest {
  org_name: string;
  email: string;
  slug?: string;
  password: string;
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

export interface ProviderCredentialResponse {
  credential_id: string;
  tenant_id: string;
  provider: string;
  integration: string;
  credential_type: string;
  enabled: boolean;
  revoked: boolean;
  allowed_actions: string[];
  allowed_side_effect_classes: string[];
  trusted_destination_hosts: string[];
  uses_platform_master_key: boolean;
  platform_master_warning?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProviderCredentialCreateRequest {
  credential_id: string;
  provider: string;
  integration?:
    | "hubspot"
    | "gmail"
    | "smtp"
    | "linkedin"
    | "salesforce"
    | "google_calendar"
    | "google_contacts"
    | "google_docs"
    | "github"
    | "generic";
  secret_value?: string;
  use_platform_master_key?: boolean;
  allowed_actions?: string[];
  allowed_side_effect_classes?: string[];
  trusted_destination_hosts?: string[];
}

export type ConnectorId = "gmail" | "google_calendar" | "google_contacts" | "google_docs";

export interface AccountOnboardingResponse {
  setup_version: number;
  completed: boolean;
  completed_at?: string | null;
  completed_by_member_id?: string | null;
  suppress_prompt: boolean;
  prompt_suppressed_at?: string | null;
  company_profile_ready: boolean;
  operating_preferences_ready: boolean;
  can_manage_connections: boolean;
  human_member: boolean;
  connections: Record<ConnectorId, boolean>;
}

export interface ProviderCredentialCreateResponse {
  credential: ProviderCredentialResponse;
  warning?: string | null;
}

export interface ProviderCredentialListResponse {
  credentials: ProviderCredentialResponse[];
}

export interface GmailOAuthAuthorizeUrlResponse {
  authorization_url: string;
  state: string;
  redirect_uri: string;
}

export interface GmailOAuthConnectRequest {
  code: string;
  state: string;
  credential_id?: string;
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

export interface AutonomyAcknowledgment {
  schema_version: number;
  disclaimer_id: string;
  disclaimer_text_hash: string;
  accepted_at: string;
  principal_id: string;
  action: string;
  side_effect_class?: string;
}

export interface AutonomyDisclaimer {
  disclaimer_id: string;
  tier: number;
  actions: string[];
  text: string;
  text_hash: string;
}

export interface AutonomyDisclaimerListResponse {
  schema_version: number;
  mode: "off" | "pilot" | "enforce";
  disclaimers: AutonomyDisclaimer[];
}

export type BrainMissionReadinessStatus =
  | "READY"
  | "BLOCKED"
  | "NEEDS_PROFILE"
  | "NEEDS_CREDENTIAL"
  | "PARTIAL";

export interface BrainMissionReadiness {
  mission_id: string;
  mission: string;
  outcome: string;
  action: string;
  tier: string;
  status: BrainMissionReadinessStatus;
  note: string;
}

export interface BrainMissionApiSpec {
  mission_id: string;
  mission: string;
  outcome: string;
  action: string;
  tier: string;
  side_effect_class: string;
  input: Record<string, unknown>;
  optional_credential: boolean;
}

export interface BrainMissionListResponse {
  schema_version: number;
  missions: BrainMissionApiSpec[];
}

export interface BrainCapabilityCheckResponse {
  schema_version: number;
  charter_source: "default" | "profile";
  profile_ready: boolean;
  summary: {
    ready: number;
    partial: number;
    blocked: number;
    needs_profile: number;
    needs_credential: number;
    total: number;
  };
  missions: BrainMissionReadiness[];
}

export interface ReviewQueueItem {
  artifact_id: string;
  artifact_type: string;
  review_status: string;
  content: Record<string, unknown>;
  metadata: Record<string, unknown>;
  mission_id?: string | null;
  task_id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ReviewQueueListResponse {
  items: ReviewQueueItem[];
  total: number;
}

export interface MissionSuccessCriterionInput {
  description: string;
  evidence?: string[];
}

export interface MissionCreateRequest {
  objective: string;
  success_criteria: MissionSuccessCriterionInput[];
  scope_limits?: string[];
  allowed_actions?: string[];
  compliance_category?: string;
  jurisdiction?: string;
}

/** Mission Composition Engine (ADR-0008) — everyday launch path. */
export interface MissionComposeRequest {
  instruction: string;
  interpretation_thread_id?: string;
}

export interface MissionComposeResponse {
  proposal_id: string;
  interpretation_thread_id: string;
  proposal_status?: string;
  instruction: string;
  raw_instruction?: string;
  normalized_instruction?: string;
  mission_brief: {
    objective: string;
    success_criteria: Array<{ description: string; measurable?: boolean }>;
    constraints: string[];
    approval_preference?: string;
    target_entities?: Array<Record<string, unknown>>;
  };
  assigned_verticals: string[];
  jobs: Array<Record<string, unknown>>;
  selected_abilities: Array<{
    job_key: string;
    action_name: string;
    selection_status: string;
    selection_reason: string;
    readiness: string;
    vertical_role?: string;
  }>;
  forbidden_actions: string[];
  allowed_actions: string[];
  allowed_actions_provenance: Record<string, unknown>;
  missing_connections: Array<Record<string, unknown>>;
  approval_gates: string[];
  planned_steps: Array<{
    step_key: string;
    sequence: number;
    title: string;
    action_name: string;
    depends_on: string[];
  }>;
  task_graph_preview: Record<string, unknown>;
  clarifications: Array<{ field: string; question: string; reason: string }>;
  ready_to_start: boolean;
  composition: Record<string, unknown>;
  grants_execution_authority: boolean;
  authority_class: string;
}

export interface MissionComposeConfirmResponse {
  mission_id: string;
  proposal_id: string;
  plan_id: string;
  allowed_actions: string[];
  forbidden_actions: string[];
  task_graph: Record<string, unknown>;
  ready_to_start: boolean;
  runtime_queued: boolean;
  grants_execution_authority: boolean;
  next_steps: string[];
}

export interface MissionIntakeQualityViolation {
  field: string;
  code: string;
  reason: string;
  severity: "required";
}

export interface MissionIntakeQualityDeniedDetail {
  code: "MISSION_INTAKE_QUALITY_DENIED";
  message: string;
  schema_version: number;
  violations: MissionIntakeQualityViolation[];
}

export interface MissionReadResponse {
  mission_id: string;
  tenant_id: string;
  objective: string;
  status: string;
  compliance_category: string;
  jurisdiction: string;
  intake: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface MissionListItem {
  mission_id: string;
  objective: string;
  status: string;
  scope_limits: string[];
  allowed_actions: string[];
  created_at: string;
  updated_at: string;
}

export interface MissionListResponse {
  missions: MissionListItem[];
  count: number;
}

export interface MissionPlanCreateRequest {
  objectives: string[];
  constraints: string[];
  assumptions: string[];
  acceptance_criteria: string[];
  planned_steps: Array<{
    sequence: number;
    title: string;
    description: string;
    depends_on: number[];
    expected_output: string;
    metadata?: Record<string, unknown>;
  }>;
  risk_notes: string[];
}

export interface MissionPlanReadResponse {
  mission_id: string;
  tenant_id: string;
  plan: Record<string, unknown>;
  updated_at: string;
  plan_id?: string | null;
  status?: string | null;
  metadata: Record<string, unknown>;
  created_at?: string | null;
}

export interface MissionTaskGraphPayload {
  schema_version: number;
  graph_status: string;
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  metadata: Record<string, unknown>;
}

export interface MissionTaskGraphReadResponse extends MissionTaskGraphPayload {
  mission_id?: string | null;
  graph_version?: number | null;
  graph_fingerprint?: string | null;
}

export interface GraphMaterializationWriteRequest {
  materialization_status: string;
  materialization_source: string;
  materialization_source_version: string;
  planner_provenance: Record<string, unknown>;
  capability_selection_provenance: Array<Record<string, unknown>>;
  graph_validation_result: Record<string, unknown>;
  operator_review?: Record<string, unknown>;
  graph_generation_metadata: Record<string, unknown>;
  deterministic_compilation_metadata: Record<string, unknown>;
  generation_notes?: string[];
}

export interface GraphMaterializationReadResponse {
  mission_id: string;
  tenant_id: string;
  materialization: Record<string, unknown>;
  updated_at: string;
}

export interface RuntimeAdmissionWriteRequest {
  /** Defaults to admitted; server validates. */
  admission_status?: string;
  /** Optional; server remints from authenticated principal and rejects UI forged identities. */
  admitted_by?: string;
  /**
   * Optional. Empty/omitted → server derives selected_nodes from compiled graph
   * after provisioning bridge capability/adapter authority.
   */
  selected_nodes?: Array<{
    node_key: string;
    runtime_task_type?: string;
    capability_id?: string;
    adapter_id?: string;
    operator_notes?: string;
  }>;
  auto_provision_authority?: boolean;
  validation_notes?: string[];
}

export interface RuntimeAdmissionReadResponse {
  mission_id: string;
  tenant_id: string;
  runtime_admission: Record<string, unknown>;
  updated_at: string;
}

export interface MissionLifecycleCompleteness {
  has_intake: boolean;
  has_plan: boolean;
  has_task_graph: boolean;
  has_materialization: boolean;
  has_runtime_admission: boolean;
  has_evidence: boolean;
  has_outcome_review: boolean;
  has_memory_promotions: boolean;
  has_retrieval_contracts: boolean;
}

export interface MissionLifecycleReadResponse {
  mission: {
    mission_id: string;
    tenant_id: string;
    objective: string;
    status: string;
    compliance_category: string;
    jurisdiction: string;
    created_at: string;
    updated_at: string;
  };
  intake: Record<string, unknown> | null;
  plan: Record<string, unknown> | null;
  task_graph: Record<string, unknown> | null;
  materialization: Record<string, unknown> | null;
  runtime_admission: Record<string, unknown> | null;
  completeness: MissionLifecycleCompleteness;
  /** Runtime ladder gaps only (plan → admit). */
  missing_next_steps: string[];
  /** Optional product close-out after workers — not pipeline failure. */
  optional_closeout_steps?: string[];
}

export interface RuntimeReadinessItem {
  code: string;
  status: string;
  message: string;
  details?: Record<string, unknown>;
}

export interface RuntimeReadinessReadResponse {
  mission_id: string;
  tenant_id: string;
  ready: boolean;
  readiness_status: string;
  checked_at: string;
  selected_node_count: number;
  checks: RuntimeReadinessItem[];
  blockers: RuntimeReadinessItem[];
  warnings: RuntimeReadinessItem[];
}

export interface RuntimeTaskMaterializationReadResponse {
  mission_id: string;
  tenant_id: string;
  materialization_status: string;
  materialization_version: number | null;
  created_execution_task_ids: string[];
  task_count: number;
  blockers: RuntimeReadinessItem[];
  warnings: RuntimeReadinessItem[];
  updated_at: string;
}

export interface RuntimeDispatchReadinessReadResponse {
  mission_id: string;
  tenant_id: string;
  readiness_status: string;
  dispatch_ready_task_ids: string[];
  not_ready_task_ids: string[];
  blocked_task_ids: string[];
  task_count: number;
  queued_task_count: number;
  blockers: Array<Record<string, unknown>>;
  warnings: Array<Record<string, unknown>>;
  checked_at: string;
}

export interface RuntimeQueueAdmissionResponse {
  admission_status: string;
  admitted_task_ids: string[];
  blocked_task_ids: string[];
  queued_task_ids: string[];
  pending_review_task_ids: string[];
  denied_tasks: Array<Record<string, string | null>>;
  blockers: Array<Record<string, unknown>>;
}

export interface BridgeRuntimeAuthorityReadResponse {
  mission_id: string;
  tenant_id: string;
  node_authorities: Array<{
    node_key: string;
    action: string;
    capability_id: string;
    adapter_id: string;
    capability_name: string;
  }>;
}

export interface AbilityTaskCreate {
  action: string;
  input: Record<string, unknown>;
  title?: string;
  description?: string;
  mission_id?: string;
  mission_objective?: string;
  idempotency_key?: string;
  approved_by?: string;
  approval_reason?: string;
  credential_reference?: {
    schema_version: number;
    credential_id: string;
    provider: string;
    credential_type: string;
  };
  autonomy_acknowledgment?: AutonomyAcknowledgment;
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

export interface BusinessProfileReadResponse {
  profile_id: string | null;
  tenant_id: string;
  status: string;
  approved_facts: Record<string, Record<string, unknown>>;
  provenance: Record<string, Record<string, unknown>>;
  schema_version: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface BusinessProfileFactUpsertRequest {
  approved_fact: Record<string, unknown>;
  provenance_metadata?: Record<string, unknown>;
}

export interface CrmRecordItem {
  id: string;
  record_type: string;
  data: Record<string, unknown>;
}

export interface CrmRecordListResponse {
  record_type: string;
  items: CrmRecordItem[];
  total: number;
}

export interface CrmTimelineResponse {
  record_type: string;
  record_id: string;
  items: Array<Record<string, unknown>>;
  total: number;
}

export interface CrmPipelineStage {
  stage: string;
  count: number;
  opportunities: Array<Record<string, unknown>>;
}

export interface CrmPipelineResponse {
  stages: CrmPipelineStage[];
}

export interface CrmSuggestion {
  suggestion_id: string;
  reason: string;
  mission_action: string;
  title: string;
  description: string;
  related_type: string;
  related_id: string;
}

export interface CrmSuggestionsResponse {
  items: CrmSuggestion[];
}

export interface ApiFailure {
  status: number;
  message: string;
  body: unknown;
}
