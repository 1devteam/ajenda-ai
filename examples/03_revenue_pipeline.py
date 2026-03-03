"""
Example 03 — Revenue Pipeline Walkthrough
==========================================
Demonstrates the full B2B sales pipeline from lead creation to closed deal,
using the RevenueAgent and DealClosingSaga.

Pipeline stages:
  1. Create a lead (manually or via AI discovery)
  2. Qualify the lead (AI scores fit, creates Opportunity if qualified)
  3. Generate a proposal (AI writes a personalised proposal)
  4. Send outreach (email the proposal — requires SMTP config)
  5. Close the deal (record the win, emit revenue event)

Or run the full pipeline in one call via the DealClosingSaga.

Run this file directly:
    cd /path/to/citadel
    python3 examples/03_revenue_pipeline.py

Author: Dev Team Lead
Built with Pride for Obex Blackvault
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.orchestration.revenue_agent import RevenueAgent
from backend.agents.tools.tool_registry import get_tool_registry


# ─── Configuration ────────────────────────────────────────────────────────────

# Your value proposition and ideal customer profile.
# These are injected into every AI prompt in the pipeline.
VALUE_PROPOSITION = (
    "Citadel AI is an autonomous agent platform that automates B2B sales research, "
    "lead qualification, and proposal generation — reducing sales cycle time by 60% "
    "and cutting research costs by 80%."
)

IDEAL_CUSTOMER_PROFILE = (
    "SMB and mid-market companies (10-500 employees) in professional services, "
    "consulting, or SaaS who have a sales team of 2-10 people and are struggling "
    "with manual lead research and inconsistent outreach."
)

# Example leads to run through the pipeline
EXAMPLE_LEADS = [
    {
        "company_name": "Nexus Consulting Group",
        "industry": "consulting",
        "company_size": "smb",
        "contact_name": "Sarah Chen",
        "contact_email": "sarah.chen@nexusconsulting.com",
        "website": "https://nexusconsulting.com",
        "notes": "Met at SaaStr 2025. Expressed interest in AI automation.",
    },
    {
        "company_name": "Cornerstone Legal Partners",
        "industry": "legal",
        "company_size": "mid",
        "contact_name": "Marcus Webb",
        "contact_email": "m.webb@cornerstonelegal.com",
        "website": "https://cornerstonelegal.com",
        "notes": "Inbound inquiry via website. Wants to automate client intake.",
    },
]


# ─── Step-by-Step Pipeline ────────────────────────────────────────────────────

async def run_step_by_step_pipeline() -> None:
    """
    Run the pipeline one step at a time for maximum visibility.
    Use this pattern when you want to inspect results at each stage
    or add custom logic between steps.
    """
    print("\n" + "=" * 60)
    print("Step-by-Step Revenue Pipeline")
    print("=" * 60)

    agent = RevenueAgent(
        tool_registry=get_tool_registry(),
        model="gpt-4.1-mini",
    )

    lead_data = EXAMPLE_LEADS[0]
    print(f"\nLead: {lead_data['company_name']}")

    # Step 1: Qualify the lead
    print("\n[1/4] Qualifying lead…")
    qualification = await agent._qualify_lead(
        lead=lead_data,
        value_proposition=VALUE_PROPOSITION,
        ideal_customer_profile=IDEAL_CUSTOMER_PROFILE,
    )
    score = qualification.get("qualification_score", 0)
    print(f"  Score:  {score:.0%}")
    print(f"  Notes:  {qualification.get('qualification_notes', '')[:100]}")
    print(f"  Fit:    {qualification.get('fit_summary', '')[:100]}")

    if score < 0.5:
        print(f"\n  Lead disqualified (score {score:.0%} < 50%). Stopping pipeline.")
        return

    # Step 2: Generate a proposal
    print("\n[2/4] Generating proposal…")
    proposal = await agent._generate_proposal(
        lead=lead_data,
        opportunity={
            "title": f"Citadel AI for {lead_data['company_name']}",
            "value": qualification.get("estimated_value", 25000),
            "probability": score,
        },
        value_proposition=VALUE_PROPOSITION,
    )
    print(f"  Title:    {proposal.get('title', '—')}")
    print(f"  Length:   {len(proposal.get('content', ''))} chars")
    print(f"  Preview:  {proposal.get('content', '')[:150].strip()}")

    # Step 3: Send outreach (dry-run if SMTP not configured)
    print("\n[3/4] Sending outreach…")
    outreach = await agent._send_outreach(
        lead=lead_data,
        proposal=proposal,
        send=True,  # Set to False to skip email sending
    )
    print(f"  Sent:     {outreach.get('sent', False)}")
    print(f"  Dry run:  {outreach.get('dry_run', True)}")
    if outreach.get("note"):
        print(f"  Note:     {outreach['note']}")

    print("\n[4/4] Pipeline complete.")
    print(f"  Lead qualified at {score:.0%} — opportunity created.")


# ─── Full Saga (One Call) ─────────────────────────────────────────────────────

async def run_full_saga() -> None:
    """
    Run the complete DealClosingSaga in a single call.

    The saga orchestrates all 7 steps with automatic compensation:
    if any step fails, all completed steps are rolled back in reverse order.

    Steps:
      1. qualify_lead        → scores the lead
      2. create_opportunity  → creates DB record if qualified
      3. generate_proposal   → writes personalised proposal
      4. save_proposal       → persists to DB
      5. record_response     → emits proposal.response_pending event
      6. close_deal          → creates Deal record
      7. record_revenue      → emits revenue.recorded event

    Returns: opportunity_id, proposal_id, deal_id, deal_value
    """
    print("\n" + "=" * 60)
    print("Full DealClosingSaga (One-Call Pipeline)")
    print("=" * 60)

    agent = RevenueAgent(
        tool_registry=get_tool_registry(),
        model="gpt-4.1-mini",
    )

    lead_data = EXAMPLE_LEADS[1]
    print(f"\nLead: {lead_data['company_name']}")
    print("Running full 7-step saga…\n")

    result = await agent.run_pipeline(
        leads=[lead_data],
        value_proposition=VALUE_PROPOSITION,
        ideal_customer_profile=IDEAL_CUSTOMER_PROFILE,
        send_outreach=False,  # Set to True to send real emails
    )

    print(f"Pipeline status: {result.get('status')}")
    print(f"Leads processed: {result.get('leads_processed', 0)}")
    print(f"Qualified:       {result.get('qualified', 0)}")
    print(f"Proposals:       {result.get('proposals_generated', 0)}")

    for item in result.get("results", []):
        print(f"\n  Company:        {item.get('company_name')}")
        print(f"  Score:          {item.get('qualification_score', 0):.0%}")
        print(f"  Opportunity ID: {item.get('opportunity_id', '—')}")
        print(f"  Proposal ID:    {item.get('proposal_id', '—')}")


# ─── Batch Lead Discovery ─────────────────────────────────────────────────────

async def run_lead_discovery() -> None:
    """
    Use the RevenueAgent to autonomously discover leads matching your ICP.

    The Researcher agent searches the web for companies that match your
    ideal customer profile, extracts contact information, and returns
    a structured list of qualified prospects.
    """
    print("\n" + "=" * 60)
    print("AI Lead Discovery")
    print("=" * 60)

    agent = RevenueAgent(
        tool_registry=get_tool_registry(),
        model="gpt-4.1-mini",
    )

    print("\nSearching for leads matching ICP…")
    leads = await agent._discover_leads(
        ideal_customer_profile=IDEAL_CUSTOMER_PROFILE,
        industry="consulting",
        max_leads=5,
    )

    print(f"Discovered {len(leads)} leads:")
    for i, lead in enumerate(leads, 1):
        print(f"\n  {i}. {lead.get('company_name', 'Unknown')}")
        print(f"     Industry: {lead.get('industry', '—')}")
        print(f"     Size:     {lead.get('company_size', '—')}")
        print(f"     Website:  {lead.get('website', '—')}")
        print(f"     Contact:  {lead.get('contact_name', '—')} <{lead.get('contact_email', '—')}>")


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main() -> None:
    """
    Run the revenue pipeline examples.
    Comment/uncomment to run specific patterns.
    """
    # Step-by-step: maximum visibility, good for debugging
    await run_step_by_step_pipeline()

    # Full saga: one call, automatic compensation on failure
    # await run_full_saga()

    # Lead discovery: AI finds prospects matching your ICP
    # await run_lead_discovery()


if __name__ == "__main__":
    asyncio.run(main())
