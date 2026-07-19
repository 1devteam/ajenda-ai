export type LaunchMissionTemplate = {
  id: string;
  title: string;
  description: string;
  /** Plain-language instruction for the composition engine — not a checklist of abilities. */
  instruction: string;
};

export const LAUNCH_MISSION_TEMPLATES: LaunchMissionTemplate[] = [
  {
    id: "lead-gen",
    title: "Lead generation",
    description: "Find and qualify prospects. Ajenda picks research, qualify, and enrich steps.",
    instruction:
      "Find three qualified leads in our target market, enrich their contact context, and prepare notes for outreach. Do not send any messages.",
  },
  {
    id: "market-research",
    title: "Market research",
    description: "Research market signals and competitors without outbound side effects.",
    instruction:
      "Research our target market and summarize key trends, three competitors, and two actionable opportunities using public and internal context.",
  },
  {
    id: "outreach",
    title: "Outreach prep",
    description: "Draft personalized introductions for review before anything is sent.",
    instruction:
      "Identify three strong prospects, draft personalized introductions for each, and bring them to me before anything is sent.",
  },
  {
    id: "roofing-example",
    title: "Austin roofing prospects",
    description: "Flagship composition example: research → qualify → draft, never send.",
    instruction:
      "Research roofing companies in Austin, identify three strong prospects, draft personalized introductions, and bring them to me before anything is sent.",
  },
  {
    id: "data-ops",
    title: "Data operations",
    description: "Organize records and prepare CRM-ready updates.",
    instruction:
      "Reconcile key account and contact records and prepare accurate CRM-ready updates with before/after evidence. Prefer internal records unless CRM is connected.",
  },
  {
    id: "scheduling",
    title: "Scheduling",
    description: "Calendar-aware meeting prep from connected calendar and records.",
    instruction:
      "Provide a calendar briefing: read calendar for upcoming commitments and prepare briefing context for the next client meetings. Do not send messages.",
  },
  {
    id: "custom",
    title: "Custom mission",
    description: "Describe any business outcome in your own words.",
    instruction: "",
  },
];
