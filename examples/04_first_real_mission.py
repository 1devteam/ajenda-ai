"""
Example 04 — First Real Mission
=================================
A complete, runnable script for your first live revenue-generating mission.

This script:
  1. Discovers 3 leads matching your ICP using the AI Researcher
  2. Qualifies each lead using the AI Analyst
  3. Generates a personalised proposal for each qualified lead
  4. Sends outreach emails (dry-run by default — set SEND_LIVE=True to send)
  5. Prints a summary report

Prerequisites:
  - OPENAI_API_KEY set in environment (or .env file)
  - For live email: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD set

Run this file:
    cd /path/to/citadel
    python3 examples/04_first_real_mission.py

To send live emails:
    SEND_LIVE=true python3 examples/04_first_real_mission.py

Author: Dev Team Lead
Built with Pride for Obex Blackvault
"""

from __future__ import annotations

import asyncio
import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.orchestration.revenue_agent import RevenueAgent
from backend.agents.tools.tool_registry import get_tool_registry

# ─── Mission Configuration ────────────────────────────────────────────────────
# Edit these to match your product and target market.

SEND_LIVE = os.environ.get("SEND_LIVE", "false").lower() == "true"
MODEL = os.environ.get("CITADEL_MODEL", "gpt-4.1-mini")

YOUR_VALUE_PROPOSITION = """
Citadel AI is an autonomous B2B sales intelligence platform. It discovers leads,
qualifies prospects, and generates personalised proposals — automatically.

Key outcomes for clients:
- 60% reduction in sales research time
- 3x more qualified leads per week
- Consistent, personalised outreach at scale
- Full pipeline visibility in a single dashboard
"""

YOUR_IDEAL_CUSTOMER_PROFILE = """
Best-fit customers:
- Company size: 10–200 employees (SMB to lower mid-market)
- Industry: professional services, consulting, SaaS, agencies
- Pain point: sales team spending 50%+ of time on manual research
- Budget signal: already paying for CRM (Salesforce, HubSpot)
- Decision maker: VP Sales, Head of Growth, or Founder/CEO
"""

TARGET_INDUSTRY = "consulting"  # Change to your target industry
MAX_LEADS = 3                   # Number of leads to discover and process


# ─── Mission Runner ───────────────────────────────────────────────────────────

async def run_first_mission() -> None:
    """Execute the first real revenue mission end-to-end."""
    start = datetime.now()
    print("\n" + "=" * 65)
    print("  CITADEL AI — FIRST REAL MISSION")
    print(f"  Started: {start.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Model:   {MODEL}")
    print(f"  Mode:    {'LIVE EMAIL' if SEND_LIVE else 'DRY RUN'}")
    print("=" * 65)

    agent = RevenueAgent(
        tool_registry=get_tool_registry(),
        model=MODEL,
    )

    results = {
        "mission_start": start.isoformat(),
        "model": MODEL,
        "send_live": SEND_LIVE,
        "leads_discovered": 0,
        "leads_qualified": 0,
        "proposals_generated": 0,
        "outreach_sent": 0,
        "pipeline": [],
    }

    # ── Phase 1: Lead Discovery ───────────────────────────────────────────────
    print(f"\n[1/4] Discovering {MAX_LEADS} leads in {TARGET_INDUSTRY}…")
    try:
        leads = await agent._discover_leads(
            ideal_customer_profile=YOUR_IDEAL_CUSTOMER_PROFILE,
            industry=TARGET_INDUSTRY,
            max_leads=MAX_LEADS,
        )
        results["leads_discovered"] = len(leads)
        print(f"  ✓ Discovered {len(leads)} leads")
        for lead in leads:
            print(f"    • {lead.get('company_name', 'Unknown')} ({lead.get('industry', '—')})")
    except Exception as e:
        print(f"  ✗ Discovery failed: {e}")
        leads = []

    if not leads:
        print("\n  No leads discovered. Check your ICP and try again.")
        return

    # ── Phase 2: Qualification ────────────────────────────────────────────────
    print(f"\n[2/4] Qualifying {len(leads)} leads…")
    qualified = []

    for lead in leads:
        company = lead.get("company_name", "Unknown")
        try:
            qual = await agent._qualify_lead(
                lead=lead,
                value_proposition=YOUR_VALUE_PROPOSITION,
                ideal_customer_profile=YOUR_IDEAL_CUSTOMER_PROFILE,
            )
            score = qual.get("qualification_score", 0)
            status = "✓ QUALIFIED" if score >= 0.6 else "✗ disqualified"
            print(f"  {status}: {company} — score {score:.0%}")

            if score >= 0.6:
                lead["qualification_score"] = score
                lead["qualification_notes"] = qual.get("qualification_notes", "")
                lead["estimated_value"] = qual.get("estimated_value", 25000)
                qualified.append(lead)
                results["leads_qualified"] += 1

            results["pipeline"].append({
                "company": company,
                "score": score,
                "qualified": score >= 0.6,
                "notes": qual.get("qualification_notes", "")[:100],
            })
        except Exception as e:
            print(f"  ✗ Qualification failed for {company}: {e}")

    if not qualified:
        print("\n  No leads qualified. Adjust your ICP or value proposition.")
        return

    # ── Phase 3: Proposal Generation ─────────────────────────────────────────
    print(f"\n[3/4] Generating proposals for {len(qualified)} qualified leads…")
    proposals = []

    for lead in qualified:
        company = lead.get("company_name", "Unknown")
        try:
            proposal = await agent._generate_proposal(
                lead=lead,
                opportunity={
                    "title": f"Citadel AI for {company}",
                    "value": lead.get("estimated_value", 25000),
                    "probability": lead.get("qualification_score", 0.7),
                },
                value_proposition=YOUR_VALUE_PROPOSITION,
            )
            print(f"  ✓ Proposal generated: {proposal.get('title', company)}")
            print(f"    Length: {len(proposal.get('content', ''))} chars")
            lead["proposal"] = proposal
            proposals.append((lead, proposal))
            results["proposals_generated"] += 1
        except Exception as e:
            print(f"  ✗ Proposal failed for {company}: {e}")

    # ── Phase 4: Outreach ─────────────────────────────────────────────────────
    mode_label = '' if SEND_LIVE else 'DRY RUN — '
    print(f"\n[4/4] Sending outreach ({mode_label}to {len(proposals)} leads)…")

    for lead, proposal in proposals:
        company = lead.get("company_name", "Unknown")
        try:
            outreach = await agent._send_outreach(
                lead=lead,
                proposal=proposal,
                send=SEND_LIVE,
            )
            sent = outreach.get("sent", False)
            dry = outreach.get("dry_run", True)
            status = "✓ SENT" if sent and not dry else "✓ dry-run OK"
            print(f"  {status}: {company} → {lead.get('contact_email', '—')}")
            if sent:
                results["outreach_sent"] += 1
        except Exception as e:
            print(f"  ✗ Outreach failed for {company}: {e}")

    # ── Summary ───────────────────────────────────────────────────────────────
    elapsed = (datetime.now() - start).total_seconds()
    results["mission_end"] = datetime.now().isoformat()
    results["elapsed_seconds"] = elapsed

    print("\n" + "=" * 65)
    print("  MISSION COMPLETE")
    print("=" * 65)
    print(f"  Leads discovered:   {results['leads_discovered']}")
    print(f"  Leads qualified:    {results['leads_qualified']}")
    print(f"  Proposals created:  {results['proposals_generated']}")
    print(f"  Outreach sent:      {results['outreach_sent']}")
    print(f"  Elapsed:            {elapsed:.1f}s")
    print(f"  Mode:               {'LIVE' if SEND_LIVE else 'DRY RUN'}")

    if not SEND_LIVE:
        print("\n  To send live emails, set SMTP credentials and run:")
        print("    SEND_LIVE=true python3 examples/04_first_real_mission.py")

    # Save results to file
    output_path = f"/tmp/mission_{start.strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Full results saved to: {output_path}")
    print("=" * 65)


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    asyncio.run(run_first_mission())
