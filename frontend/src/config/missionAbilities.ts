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
  { action: "web.page_read", label: "Web page read" },
  { action: "web.browser_session", label: "Web browser session" },
  { action: "web.open_write", label: "Web open write" },
  { action: "web.research", label: "Web research" },
  { action: "http.request", label: "HTTP request" },
  { action: "sales.research", label: "Sales / CRM research" },
  { action: "crm.research", label: "CRM research (HubSpot)" },
  { action: "gtm.lead_enrich", label: "Lead enrich" },
  { action: "gtm.email_draft", label: "Draft email" },
  { action: "gtm.email_check", label: "Check inbox" },
  { action: "gtm.email_send", label: "Send email" },
  { action: "gtm.crm_upsert", label: "CRM upsert" },
  { action: "document.generate", label: "Generate document artifact" },
  { action: "document.search", label: "Search clerical library" },
  { action: "document.read", label: "Read document artifact" },
  { action: "linkedin.profile_read", label: "LinkedIn profile read" },
  { action: "salesforce.soql_read", label: "Salesforce SOQL read" },
  { action: "google_calendar.events_read", label: "Google Calendar read" },
  { action: "github.repo_read", label: "GitHub repo read" },
  { action: "retrieval.hybrid_search", label: "Hybrid memory retrieval" },
] as const;

/** Ordered actions for the M11 capstone outreach bundle in Mission Dispatch. */
export const CAPSTONE_OUTREACH_ACTIONS = [
  "sales.research",
  "gtm.email_draft",
  "gtm.email_send",
  "gtm.crm_upsert",
] as const;

export const MISSION_ABILITY_PRESETS: MissionAbilityPreset[] = [
  {
    action: "web.search",
    title: "Web search",
    description: "Search the public web for market or company signals.",
    input: { query: "roofing contractors Austin", limit: 5 },
  },
  {
    action: "web.page_read",
    title: "Web page read",
    description: "Fetch a public HTTPS page and extract title/text (not a browser).",
    input: { url: "https://example.com" },
  },
  {
    action: "web.browser_session",
    title: "Web browser session",
    description: "Ephemeral headless browser navigate+extract (AJENDA_BROWSER_SESSION_ENABLED).",
    input: { url: "https://example.com", wait_until: "domcontentloaded" },
  },
  {
    action: "web.open_write",
    title: "Web open write",
    description: "Public POST/PUT/PATCH with rate limit + idempotency (AJENDA_OPEN_WRITE_ENABLED).",
    input: {
      url: "https://httpbin.org/post",
      method: "POST",
      json_body: { hello: "ajenda" },
      idempotency_key: "demo-open-write-key-001",
    },
  },
  {
    action: "web.research",
    title: "Web research",
    description: "Hybrid research: internal records + optional public search/page.",
    input: { query: "roofing contractors Austin", include_public_search: true, limit: 5 },
  },
  {
    action: "http.request",
    title: "HTTP request",
    description: "Governed HTTPS call (GET/HEAD read; write methods need side-effect auth).",
    input: { method: "GET", url: "https://example.com", timeout_seconds: 5 },
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
    description: "Draft a personalized greeting email and persist to the review queue.",
    input: {
      recipient: "prospect@example.com",
      topic: "Quick introduction",
      tone: "professional",
      context: { goal: "Warm greeting for a new roofing lead." },
    },
  },
  {
    action: "sales.research",
    title: "Sales research",
    description: "Research a lead with Ajenda brain; connect CRM for enriched external context.",
    input: { lead: { company: "HubSpot", domain: "hubspot.com" } },
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
    description: "Read recent inbox messages through connected Gmail (inbox is Gmail API only today).",
    input: { query: "in:inbox", limit: 3 },
    provider: "external_email",
    credentialType: "api_key",
    requiresCredential: true,
  },
  {
    action: "gtm.email_send",
    title: "Send approved email",
    description:
      "Send an approved draft via Gmail OAuth, tenant SMTP (any provider), or Ajenda platform email.",
    input: {
      to: "prospect@example.com",
      artifact_id: "pitch_email-<artifact-id>",
      context: { capstone: true },
    },
    provider: "external_email",
    credentialType: "api_key",
    requiresCredential: true,
  },
  {
    action: "gtm.crm_upsert",
    title: "CRM upsert",
    description: "Log or update a contact in the internal pipeline or platform HubSpot.",
    input: {
      record_type: "contact",
      data: {
        email: "jordan.lee@example.com",
        firstname: "Jordan",
        lastname: "Lee",
        company: "Example Co",
      },
    },
  },
  {
    action: "document.generate",
    title: "Generate document",
    description: "Generate a governed document artifact (ROI brief, pitch email, etc.).",
    input: {
      artifact_type: "roi_brief",
      topic: "Ajenda clerical worker pilot ROI",
      tone: "professional",
      context: { audience: "VP Operations" },
    },
  },
  {
    action: "document.search",
    title: "Search clerical library",
    description: "Find governed document artifacts in the tenant clerical library.",
    input: { query: "Ajenda capability ROI", artifact_type: "roi_brief", limit: 5 },
  },
  {
    action: "document.read",
    title: "Read document artifact",
    description: "Read a specific document artifact by ID from the clerical library.",
    input: { artifact_id: "roi_brief-ajenda-pilot" },
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
  {
    action: "github.repo_read",
    title: "GitHub repo read",
    description: "Read public repository metadata from GitHub.",
    input: { owner: "1devteam", repo: "ajenda-ai" },
    provider: "external_read_provider",
    credentialType: "api_key",
    requiresCredential: true,
  },
  {
    action: "retrieval.hybrid_search",
    title: "Hybrid memory retrieval",
    description: "Search governed internal records and ephemeral mission memory.",
    input: { query: "approved outreach playbook", limit: 5 },
  },
];

export const CAPSTONE_OUTREACH_PRESETS: MissionAbilityPreset[] = CAPSTONE_OUTREACH_ACTIONS.map(
  (action) => MISSION_ABILITY_PRESETS.find((preset) => preset.action === action)!,
);