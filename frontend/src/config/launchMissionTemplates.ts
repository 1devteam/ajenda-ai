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
    id: "roofing-example",
    title: "Austin roofing (flagship)",
    description: "Research → qualify → draft. Never send.",
    instruction:
      "Research roofing companies in Austin, identify three strong prospects, draft personalized introductions, and bring them to me before anything is sent.",
  },
];
