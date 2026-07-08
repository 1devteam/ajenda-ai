export type LaunchMissionTemplate = {
  id: string;
  title: string;
  description: string;
  objective: string;
  successCriterion: string;
  scopeLimit: string;
  allowedActions: string[];
};

export const LAUNCH_MISSION_TEMPLATES: LaunchMissionTemplate[] = [
  {
    id: "lead-gen",
    title: "Lead Generation",
    description: "Find and qualify prospects with enriched context.",
    objective:
      "Find three qualified leads in our target market and document company, contact, and qualification notes.",
    successCriterion:
      "Three leads are documented with company name, contact path, and qualification rationale ready for outreach.",
    scopeLimit: "Target segment, three leads, enrichment deliverables",
    allowedActions: ["crm.research", "gtm.lead_enrich", "sales.research", "web.search"],
  },
  {
    id: "market-research",
    title: "Market Research",
    description: "Research market signals and competitive context.",
    objective:
      "Research our target market and summarize key trends, competitors, and opportunities for our offer.",
    successCriterion:
      "A structured brief covers market size signals, three competitors, and two actionable opportunities.",
    scopeLimit: "Public web and governed memory sources only",
    allowedActions: ["web.search", "web.research", "retrieval.hybrid_search", "sales.research"],
  },
  {
    id: "outreach",
    title: "Outreach",
    description: "Draft and review personalized outreach sequences.",
    objective:
      "Draft personalized greeting emails for qualified prospects and prepare them for human review before send.",
    successCriterion:
      "Draft emails exist for each target prospect with recipient context and review-ready copy.",
    scopeLimit: "Draft-only unless explicitly approved for send",
    allowedActions: ["gtm.email_draft", "gtm.lead_enrich", "crm.research", "sales.research"],
  },
  {
    id: "data-ops",
    title: "Data Operations",
    description: "Organize records, CRM updates, and internal data work.",
    objective:
      "Reconcile key account and contact records and prepare accurate CRM-ready updates.",
    successCriterion:
      "Record changes are documented with before/after context and evidence for each update.",
    scopeLimit: "Tenant-owned records and approved CRM paths",
    allowedActions: ["record.search", "crm.research", "gtm.crm_upsert", "retrieval.hybrid_search"],
  },
  {
    id: "scheduling",
    title: "Scheduling",
    description: "Calendar-aware coordination and meeting prep.",
    objective:
      "Review upcoming calendar commitments and prepare briefing context for the next client meetings.",
    successCriterion:
      "Meeting briefs include attendee context, agenda suggestions, and linked account notes.",
    scopeLimit: "Read calendar and internal records; no sends without approval",
    allowedActions: ["google_calendar.events_read", "retrieval.hybrid_search", "record.search"],
  },
  {
    id: "custom",
    title: "Custom Mission",
    description: "Start from a blank goal and define your own outcome.",
    objective: "",
    successCriterion: "",
    scopeLimit: "",
    allowedActions: ["gtm.lead_enrich", "gtm.email_draft", "crm.research", "retrieval.hybrid_search"],
  },
];