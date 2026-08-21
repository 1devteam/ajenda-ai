export type BrainMissionCapstoneStep = {
  step: number;
  label: string;
  action: string;
  description: string;
  input: Record<string, unknown>;
  requiresCredential?: boolean;
  provider?: string;
};

export type BrainMissionTemplate = {
  missionId: string;
  title: string;
  description: string;
  action: string;
  tier: string;
  input: Record<string, unknown>;
  requiresCredential?: boolean;
  provider?: string;
  capstone?: boolean;
  capstoneSteps?: BrainMissionCapstoneStep[];
};

export const BRAIN_MISSION_TEMPLATES: BrainMissionTemplate[] = [
  {
    missionId: "M1",
    title: "Remember who we are",
    description: "Search governed memory for company facts from your business profile.",
    action: "retrieval.hybrid_search",
    tier: "prepare/read",
    input: { query: "Ajenda products services target customers differentiators", limit: 5 },
  },
  {
    missionId: "M2",
    title: "Find accounts in our book",
    description: "Search internal account records synced from business profile.",
    action: "record.search",
    tier: "read",
    input: { record_type: "account", query: "", limit: 5 },
  },
  {
    missionId: "M3",
    title: "Research a prospect on the web",
    description: "Combine business context with public web signals.",
    action: "web.research",
    tier: "prepare/read",
    input: {
      query: "governed mission runtime SaaS",
      company: "",
      domain: "",
      fetch_public_page: true,
      limit: 3,
    },
  },
  {
    missionId: "M4",
    title: "Qualify an inbound lead",
    description: "Score fit and explain qualification.",
    action: "sales.qualify",
    tier: "prepare",
    input: { lead: { company: "Northwind Logistics", title: "VP Operations", source: "inbound" } },
  },
  {
    missionId: "M5",
    title: "Recommend next action",
    description: "Prioritize pipeline and suggest the next step.",
    action: "sales.recommend_next_action",
    tier: "prepare",
    input: { lead: { company: "Northwind Logistics", score: 72, stage: "discovery" } },
  },
  {
    missionId: "M6",
    title: "Enrich company hints",
    description: "Structured enrich payload for outreach prep.",
    action: "gtm.lead_enrich",
    tier: "prepare",
    input: { company: "Northwind Logistics", domain: "northwind-logistics.example" },
  },
  {
    missionId: "M7",
    title: "Draft introduction email",
    description: "Prepare (not send) a first-touch email.",
    action: "gtm.email_draft",
    tier: "prepare",
    input: {
      recipient: "ops@northwind-logistics.example",
      topic: "Introduction",
      tone: "professional",
      context: { goal: "Introduce your clerical worker pilot." },
    },
  },
  {
    missionId: "M8",
    title: "Draft sales follow-up",
    description: "Prepare follow-up copy and activity context.",
    action: "sales.draft_followup",
    tier: "prepare",
    input: {
      recipient_name: "Jordan",
      topic: "workflow review after intro",
      tone: "professional",
      context: { company: "Northwind Logistics" },
    },
  },
  {
    missionId: "M9",
    title: "Log prospect in pipeline",
    description: "Internal CRM write — no external HubSpot required.",
    action: "gtm.crm_upsert",
    tier: "perform (internal)",
    input: {
      record_type: "contact",
      data: {
        email: "jordan.lee@northwind-logistics.example",
        firstname: "Jordan",
        lastname: "Lee",
        company: "Northwind Logistics",
      },
    },
  },
  {
    missionId: "M10",
    title: "Research lead against records",
    description: "Brain-first sales research; CRM plugin is optional.",
    action: "sales.research",
    tier: "prepare/read",
    input: { lead: { company: "Northwind Logistics", domain: "northwind-logistics.example" } },
  },
  {
    missionId: "M11",
    title: "Capstone outreach loop",
    description: "Research → draft → review → send → CRM. Opens the guided capstone sequence.",
    action: "gtm.email_send",
    tier: "perform (capstone)",
    input: {
      to: "ops@northwind-logistics.example",
      context: { capstone: true },
    },
    requiresCredential: true,
    provider: "external_email",
    capstone: true,
    capstoneSteps: [
      {
        step: 1,
        label: "Research prospect",
        action: "sales.research",
        description: "Brain-first research against internal records (CRM plugin optional).",
        input: { lead: { company: "Northwind Logistics", domain: "northwind-logistics.example" } },
      },
      {
        step: 2,
        label: "Draft introduction",
        action: "gtm.email_draft",
        description: "Generate pitch email artifact (LLM when configured).",
        input: {
          recipient: "ops@northwind-logistics.example",
          topic: "Ajenda clerical worker pilot",
          tone: "professional",
          context: { goal: "Capstone step 2 — governed draft." },
        },
      },
      {
        step: 3,
        label: "Approve in review queue",
        action: "review_queue",
        description: "Refresh the draft review queue below and approve the artifact for send.",
        input: {},
      },
      {
        step: 4,
        label: "Send approved draft",
        action: "gtm.email_send",
        description:
          "Send using Gmail, SMTP, or ajenda-email platform credential with artifact_id from the approved draft.",
        input: {
          to: "ops@northwind-logistics.example",
          context: { capstone: true },
        },
        requiresCredential: true,
        provider: "external_email",
      },
      {
        step: 5,
        label: "Log in CRM",
        action: "gtm.crm_upsert",
        description: "Record the outreach in internal pipeline / platform HubSpot.",
        input: {
          record_type: "contact",
          data: {
            email: "jordan.lee@northwind-logistics.example",
            firstname: "Jordan",
            lastname: "Lee",
            company: "Northwind Logistics",
          },
        },
      },
    ],
  },
  {
    missionId: "M12",
    title: "Search clerical library",
    description: "Find ROI briefs, capability resumes, and other governed document artifacts.",
    action: "document.search",
    tier: "prepare/read",
    input: { query: "Ajenda capability ROI", artifact_type: "roi_brief", limit: 5 },
  },
];
