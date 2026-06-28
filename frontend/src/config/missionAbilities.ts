export type MissionAbilityPreset = {
  action: string;
  title: string;
  description: string;
  input: Record<string, unknown>;
  provider?: string;
  credentialType?: string;
  requiresCredential?: boolean;
};

export const MISSION_ALLOWED_ACTION_OPTIONS = [
  { action: "web.search", label: "Web search" },
  { action: "sales.research", label: "Sales / CRM research" },
  { action: "crm.research", label: "CRM research (HubSpot)" },
  { action: "gtm.lead_enrich", label: "Lead enrich" },
  { action: "gtm.email_draft", label: "Draft email" },
  { action: "gtm.email_check", label: "Check inbox" },
  { action: "gtm.email_send", label: "Send email" },
  { action: "gtm.crm_upsert", label: "CRM upsert" },
  { action: "linkedin.profile_read", label: "LinkedIn profile read" },
  { action: "salesforce.soql_read", label: "Salesforce SOQL read" },
  { action: "google_calendar.events_read", label: "Google Calendar read" },
] as const;

export const MISSION_ABILITY_PRESETS: MissionAbilityPreset[] = [
  {
    action: "web.search",
    title: "Web search",
    description: "Search the public web for market or company signals.",
    input: { query: "roofing contractors Austin", limit: 5 },
  },
  {
    action: "gtm.lead_enrich",
    title: "Lead enrich",
    description: "Enrich a lead with structured company and contact hints.",
    input: { company: "Example Roofing Co", domain: "example-roofing.com" },
  },
  {
    action: "gtm.email_draft",
    title: "Draft greeting email",
    description: "Draft a personalized greeting email for a prospect.",
    input: {
      to: "prospect@example.com",
      subject: "Quick introduction",
      body: "Draft a warm greeting email for a new roofing lead.",
    },
  },
  {
    action: "sales.research",
    title: "Sales research",
    description: "Research a lead with Ajenda brain and optional CRM context.",
    input: { lead: { company: "HubSpot", domain: "hubspot.com" } },
    provider: "external_crm",
    credentialType: "api_key",
    requiresCredential: true,
  },
  {
    action: "crm.research",
    title: "CRM research",
    description: "Research a company through the connected HubSpot CRM adapter.",
    input: { lead: { company: "HubSpot", domain: "hubspot.com" } },
    provider: "external_crm",
    credentialType: "api_key",
    requiresCredential: true,
  },
  {
    action: "gtm.email_check",
    title: "Check inbox",
    description: "Read recent inbox messages through connected Gmail.",
    input: { query: "in:inbox", limit: 3 },
    provider: "external_email",
    credentialType: "api_key",
    requiresCredential: true,
  },
  {
    action: "linkedin.profile_read",
    title: "LinkedIn profile read",
    description: "Read the connected member profile via LinkedIn userinfo.",
    input: {},
    provider: "external_read_provider",
    credentialType: "api_key",
    requiresCredential: true,
  },
  {
    action: "salesforce.soql_read",
    title: "Salesforce SOQL read",
    description: "Run a read-only SELECT query against the connected Salesforce org.",
    input: { soql: "SELECT Id, Name FROM Account LIMIT 5" },
    provider: "external_read_provider",
    credentialType: "api_key",
    requiresCredential: true,
  },
  {
    action: "google_calendar.events_read",
    title: "Google Calendar read",
    description: "List upcoming events from the connected Google Calendar.",
    input: { calendar_id: "primary", limit: 5 },
    provider: "external_read_provider",
    credentialType: "api_key",
    requiresCredential: true,
  },
];