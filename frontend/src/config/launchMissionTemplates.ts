export type LaunchMissionTemplate = {
  id: string;
  title: string;
  description: string;
  /** Plain-language instruction for the composition engine — not a checklist of abilities. */
  instruction: string;
};

/**
 * Starters only. They fill the mission query box.
 * They never lock skills — composition chooses work from Ajenda's full catalog.
 */
export const LAUNCH_MISSION_TEMPLATES: LaunchMissionTemplate[] = [
  {
    id: "lead-gen",
    title: "Lead generation",
    description: "Find and qualify prospects. Draft only — no outbound send.",
    instruction:
      "Find three qualified leads in our target market, enrich their contact context, and prepare notes for outreach. Do not send any messages.",
  },
  {
    id: "market-research",
    title: "Market research",
    description: "Trends, competitors, and opportunities without side effects.",
    instruction:
      "Research our target market and summarize key trends, three competitors, and two actionable opportunities using public and internal context.",
  },
  {
    id: "outreach",
    title: "Outreach prep",
    description: "Personalized drafts for review before anything is sent.",
    instruction:
      "Identify three strong prospects, draft personalized introductions for each, and bring them to me before anything is sent.",
  },
  {
    id: "ajenda-introduction",
    title: "Ajenda self-introduction",
    description: "Use approved Ajenda facts to prepare a truthful introduction. Never send.",
    instruction:
      "Search Ajenda's approved business profile and governed internal memory, then prepare an evidence-backed company brief and a draft introduction explaining who Ajenda is, what it provides, who it serves, and why it is different. Do not browse the web, contact anyone, send email, modify CRM records, or perform any external action.",
  },
];
