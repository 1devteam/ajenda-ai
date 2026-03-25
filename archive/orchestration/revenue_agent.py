"""
Revenue Agent — Phase 5 (v6.4)

The RevenueAgent orchestrates the full sales cycle using the WorkforceCoordinator
(Phase 4) as its execution engine. It is responsible for:

  1. Lead discovery     — delegates to Researcher + Browser agents
  2. Lead qualification — delegates to Analyst agent (score 0.0–1.0)
  3. Proposal generation— delegates to Writer agent (markdown proposal)
  4. Outreach dispatch  — delegates to Poster agent (email/LinkedIn/Twitter)
  5. Response tracking  — polls EventStore for response events
  6. Deal recording     — creates Deal record when opportunity closes

The RevenueAgent is NOT a LangChain agent. It is a pure Python orchestrator
that uses the WorkforceCoordinator for all LLM-backed sub-tasks.

Built with Pride for Obex Blackvault
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain value objects
# ---------------------------------------------------------------------------


class LeadStatus(str, Enum):
    NEW = "new"
    RESEARCHED = "researched"
    QUALIFIED = "qualified"
    CONVERTED = "converted"
    DISQUALIFIED = "disqualified"


class OpportunityStage(str, Enum):
    DISCOVERY = "discovery"
    PROPOSAL = "proposal"
    NEGOTIATION = "negotiation"
    CLOSED_WON = "closed_won"
    CLOSED_LOST = "closed_lost"


class ProposalStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    VIEWED = "viewed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class LeadRecord:
    """In-memory representation of a lead during the revenue pipeline."""

    id: str
    company_name: str
    tenant_id: str
    status: LeadStatus = LeadStatus.NEW
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_title: Optional[str] = None
    website: Optional[str] = None
    linkedin_url: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    location: Optional[str] = None
    qualification_score: Optional[float] = None
    qualification_notes: Optional[str] = None
    research_data: Dict[str, Any] = field(default_factory=dict)
    source: Optional[str] = None
    source_url: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class OpportunityRecord:
    """In-memory representation of an opportunity during the revenue pipeline."""

    id: str
    lead_id: str
    tenant_id: str
    name: str
    stage: OpportunityStage = OpportunityStage.DISCOVERY
    estimated_value: Optional[float] = None
    probability: Optional[float] = None
    description: Optional[str] = None
    close_reason: Optional[str] = None
    actual_value: Optional[float] = None
    closed_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ProposalRecord:
    """In-memory representation of a proposal during the revenue pipeline."""

    id: str
    opportunity_id: str
    tenant_id: str
    title: str
    body: str
    status: ProposalStatus = ProposalStatus.DRAFT
    executive_summary: Optional[str] = None
    call_to_action: Optional[str] = None
    sent_via: Optional[str] = None
    sent_to_email: Optional[str] = None
    sent_to_linkedin: Optional[str] = None
    version: int = 1
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RevenueRunResult:
    """Result of a complete revenue pipeline run."""

    run_id: str
    tenant_id: str
    goal: str
    leads_discovered: int = 0
    leads_qualified: int = 0
    leads_disqualified: int = 0
    opportunities_created: int = 0
    proposals_generated: int = 0
    proposals_sent: int = 0
    deals_closed: int = 0
    total_pipeline_value: float = 0.0
    leads: List[LeadRecord] = field(default_factory=list)
    opportunities: List[OpportunityRecord] = field(default_factory=list)
    proposals: List[ProposalRecord] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    status: str = "running"


# ---------------------------------------------------------------------------
# RevenueAgent
# ---------------------------------------------------------------------------


class RevenueAgent:
    """
    Orchestrates the full sales pipeline using the WorkforceCoordinator.

    The RevenueAgent is stateless between calls — all state is tracked in
    ``RevenueRunResult`` and persisted to the database by the caller.

    Parameters
    ----------
    workforce_coordinator:
        A configured WorkforceCoordinator instance (Phase 4).
    qualification_threshold:
        Minimum score (0.0–1.0) for a lead to qualify as an opportunity.
        Default: 0.6 (60%).
    max_leads_per_run:
        Maximum number of leads to discover and process per run.
        Default: 10.
    event_store:
        Optional EventStore for emitting pipeline events.
    """

    RESEARCHER_PROMPT_TEMPLATE = """
You are a B2B sales researcher. Your goal is to find {count} companies that match
this profile: {target_profile}

For each company, provide:
1. Company name
2. Website URL
3. Industry
4. Estimated company size (startup/smb/mid-market/enterprise)
5. Location
6. Why they are a good fit for: {value_proposition}

Return a JSON array of company objects with keys:
company_name, website, industry, company_size, location, fit_reason, source_url

Focus on companies that are actively growing and would benefit most from the solution.
"""

    QUALIFICATION_PROMPT_TEMPLATE = """
You are a B2B sales analyst. Qualify this lead for our solution.

Company: {company_name}
Industry: {industry}
Size: {company_size}
Research data: {research_summary}

Our value proposition: {value_proposition}
Ideal customer profile: {ideal_customer_profile}

Provide a qualification assessment with:
1. qualification_score: float 0.0-1.0 (0=poor fit, 1=perfect fit)
2. qualification_notes: 2-3 sentence explanation
3. contact_title: best job title to target (e.g. "VP of Operations")
4. estimated_value: estimated deal value in USD (integer)
5. probability: probability of closing 0.0-1.0

Return as JSON with these exact keys.
"""

    PROPOSAL_PROMPT_TEMPLATE = """
You are an expert B2B sales writer. Write a compelling sales proposal.

Target company: {company_name}
Contact title: {contact_title}
Industry: {industry}
Qualification notes: {qualification_notes}
Estimated value: ${estimated_value}

Our solution: {value_proposition}
Key benefits for this company: {fit_reason}

Write a professional proposal with:
1. title: compelling subject line (max 80 chars)
2. executive_summary: 2-3 sentences (max 150 words)
3. body: full proposal in markdown (400-600 words)
   - Problem statement specific to their industry
   - Our solution and how it addresses their specific situation
   - 3 concrete ROI metrics with numbers
   - Social proof (reference similar companies)
   - Clear next step
4. call_to_action: specific ask (e.g. "Schedule a 30-minute demo this week")

Return as JSON with keys: title, executive_summary, body, call_to_action
"""

    def __init__(
        self,
        workforce_coordinator: Any,
        qualification_threshold: float = 0.6,
        max_leads_per_run: int = 10,
        event_store: Optional[Any] = None,
    ) -> None:
        self.coordinator = workforce_coordinator
        self.qualification_threshold = qualification_threshold
        self.max_leads_per_run = max_leads_per_run
        self.event_store = event_store

    async def run_pipeline(
        self,
        goal: str,
        tenant_id: str,
        value_proposition: str,
        target_profile: str,
        ideal_customer_profile: str,
        generate_proposals: bool = True,
        send_outreach: bool = False,
    ) -> RevenueRunResult:
        """
        Execute the full revenue pipeline.

        Parameters
        ----------
        goal:
            High-level goal description (e.g. "Find 10 retail loss-prevention leads").
        tenant_id:
            Tenant context for all operations.
        value_proposition:
            What Citadel offers (used in research and proposal prompts).
        target_profile:
            Description of ideal target company (used in research prompt).
        ideal_customer_profile:
            ICP criteria for qualification (used in qualification prompt).
        generate_proposals:
            Whether to generate proposals for qualified leads. Default: True.
        send_outreach:
            Whether to send outreach via the Poster agent. Default: False.
            Set to True only when real API credentials are configured.
        """
        run_id = f"rev_{uuid.uuid4().hex[:12]}"
        result = RevenueRunResult(
            run_id=run_id,
            tenant_id=tenant_id,
            goal=goal,
        )

        logger.info(
            "RevenueAgent.run_pipeline started",
            extra={"run_id": run_id, "tenant_id": tenant_id, "goal": goal},
        )

        try:
            # ----------------------------------------------------------------
            # Step 1: Lead Discovery
            # ----------------------------------------------------------------
            leads = await self._discover_leads(
                tenant_id=tenant_id,
                target_profile=target_profile,
                value_proposition=value_proposition,
                count=self.max_leads_per_run,
            )
            result.leads = leads
            result.leads_discovered = len(leads)
            logger.info(f"[{run_id}] Discovered {len(leads)} leads")

            # ----------------------------------------------------------------
            # Step 2: Lead Qualification
            # ----------------------------------------------------------------
            qualified: List[LeadRecord] = []
            for lead in leads:
                try:
                    score, notes, contact_title, est_value, prob = await self._qualify_lead(
                        lead=lead,
                        value_proposition=value_proposition,
                        ideal_customer_profile=ideal_customer_profile,
                    )
                    lead.qualification_score = score
                    lead.qualification_notes = notes
                    if contact_title:
                        lead.contact_title = contact_title

                    if score >= self.qualification_threshold:
                        lead.status = LeadStatus.QUALIFIED
                        qualified.append(lead)
                        result.leads_qualified += 1

                        # Create opportunity
                        opp = OpportunityRecord(
                            id=f"opp_{uuid.uuid4().hex[:12]}",
                            lead_id=lead.id,
                            tenant_id=tenant_id,
                            name=f"{lead.company_name} — {value_proposition[:50]}",
                            stage=OpportunityStage.DISCOVERY,
                            estimated_value=est_value,
                            probability=prob,
                        )
                        result.opportunities.append(opp)
                        result.opportunities_created += 1
                        if est_value:
                            result.total_pipeline_value += est_value
                    else:
                        lead.status = LeadStatus.DISQUALIFIED
                        result.leads_disqualified += 1

                except Exception as exc:
                    logger.warning(
                        f"[{run_id}] Qualification failed for {lead.company_name}: {exc}"
                    )
                    result.errors.append(f"Qualification failed for {lead.company_name}: {exc}")

            logger.info(
                f"[{run_id}] Qualified {result.leads_qualified}/{result.leads_discovered} leads"
            )

            # ----------------------------------------------------------------
            # Step 3: Proposal Generation
            # ----------------------------------------------------------------
            if generate_proposals and qualified:
                for lead, opp in zip(qualified, result.opportunities):
                    try:
                        proposal = await self._generate_proposal(
                            lead=lead,
                            opportunity=opp,
                            value_proposition=value_proposition,
                        )
                        result.proposals.append(proposal)
                        result.proposals_generated += 1
                        opp.stage = OpportunityStage.PROPOSAL

                    except Exception as exc:
                        logger.warning(
                            f"[{run_id}] Proposal generation failed for "
                            f"{lead.company_name}: {exc}"
                        )
                        result.errors.append(
                            f"Proposal generation failed for {lead.company_name}: {exc}"
                        )

            # ----------------------------------------------------------------
            # Step 4: Outreach (optional)
            # ----------------------------------------------------------------
            if send_outreach and result.proposals:
                for proposal in result.proposals:
                    try:
                        sent = await self._send_outreach(proposal=proposal)
                        if sent:
                            proposal.status = ProposalStatus.SENT
                            result.proposals_sent += 1
                    except Exception as exc:
                        logger.warning(
                            f"[{run_id}] Outreach failed for proposal " f"{proposal.id}: {exc}"
                        )
                        result.errors.append(f"Outreach failed for proposal {proposal.id}: {exc}")

            result.status = "completed"

        except Exception as exc:
            logger.error(f"[{run_id}] Revenue pipeline failed: {exc}", exc_info=True)
            result.status = "failed"
            result.errors.append(f"Pipeline error: {exc}")

        finally:
            result.completed_at = datetime.utcnow()

        logger.info(
            f"[{run_id}] Pipeline complete: {result.leads_discovered} discovered, "
            f"{result.leads_qualified} qualified, {result.proposals_generated} proposals, "
            f"${result.total_pipeline_value:,.0f} pipeline value"
        )

        return result

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    async def _discover_leads(
        self,
        tenant_id: str,
        target_profile: str,
        value_proposition: str,
        count: int,
    ) -> List[LeadRecord]:
        """Use the WorkforceCoordinator Researcher agent to discover leads."""
        prompt = self.RESEARCHER_PROMPT_TEMPLATE.format(
            count=count,
            target_profile=target_profile,
            value_proposition=value_proposition,
        )

        try:
            wf_result = await self.coordinator.run(
                goal=prompt,
                tenant_id=tenant_id,
                roles=["researcher"],
                pipeline_type="parallel",
            )

            # Parse the result — the coordinator returns a synthesised string
            raw = wf_result.get("result", "") or wf_result.get("output", "")
            companies = self._parse_json_list(raw)

            leads: List[LeadRecord] = []
            for item in companies[:count]:
                if not isinstance(item, dict):
                    continue
                lead = LeadRecord(
                    id=f"lead_{uuid.uuid4().hex[:12]}",
                    company_name=item.get("company_name", "Unknown"),
                    tenant_id=tenant_id,
                    website=item.get("website"),
                    industry=item.get("industry"),
                    company_size=item.get("company_size"),
                    location=item.get("location"),
                    research_data=item,
                    source="web_search",
                    source_url=item.get("source_url"),
                )
                leads.append(lead)

            return leads

        except Exception as exc:
            logger.warning(f"Lead discovery via coordinator failed: {exc}")
            # Return empty list — caller handles gracefully
            return []

    async def _qualify_lead(
        self,
        lead: LeadRecord,
        value_proposition: str,
        ideal_customer_profile: str,
    ):
        """Use the WorkforceCoordinator Analyst agent to qualify a lead."""
        research_summary = json.dumps(lead.research_data, indent=2)[:1000]
        prompt = self.QUALIFICATION_PROMPT_TEMPLATE.format(
            company_name=lead.company_name,
            industry=lead.industry or "Unknown",
            company_size=lead.company_size or "Unknown",
            research_summary=research_summary,
            value_proposition=value_proposition,
            ideal_customer_profile=ideal_customer_profile,
        )

        wf_result = await self.coordinator.run(
            goal=prompt,
            tenant_id=lead.tenant_id,
            roles=["analyst"],
            pipeline_type="parallel",
        )

        raw = wf_result.get("result", "") or wf_result.get("output", "")
        data = self._parse_json_object(raw)

        score = float(data.get("qualification_score", 0.0))
        notes = data.get("qualification_notes", "")
        contact_title = data.get("contact_title")
        est_value = data.get("estimated_value")
        if est_value is not None:
            try:
                est_value = float(est_value)
            except (TypeError, ValueError):
                est_value = None
        prob = data.get("probability")
        if prob is not None:
            try:
                prob = float(prob)
            except (TypeError, ValueError):
                prob = None

        return score, notes, contact_title, est_value, prob

    async def _generate_proposal(
        self,
        lead: LeadRecord,
        opportunity: OpportunityRecord,
        value_proposition: str,
    ) -> ProposalRecord:
        """Use the WorkforceCoordinator Writer agent to generate a proposal."""
        prompt = self.PROPOSAL_PROMPT_TEMPLATE.format(
            company_name=lead.company_name,
            contact_title=lead.contact_title or "Decision Maker",
            industry=lead.industry or "your industry",
            qualification_notes=lead.qualification_notes or "",
            estimated_value=int(opportunity.estimated_value or 0),
            value_proposition=value_proposition,
            fit_reason=lead.research_data.get("fit_reason", ""),
        )

        wf_result = await self.coordinator.run(
            goal=prompt,
            tenant_id=lead.tenant_id,
            roles=["writer"],
            pipeline_type="parallel",
        )

        raw = wf_result.get("result", "") or wf_result.get("output", "")
        data = self._parse_json_object(raw)

        proposal = ProposalRecord(
            id=f"prop_{uuid.uuid4().hex[:12]}",
            opportunity_id=opportunity.id,
            tenant_id=lead.tenant_id,
            title=data.get("title", f"Proposal for {lead.company_name}"),
            executive_summary=data.get("executive_summary"),
            body=data.get("body", raw),
            call_to_action=data.get("call_to_action"),
        )
        return proposal

    async def _send_outreach(self, proposal: ProposalRecord) -> bool:
        """
        Dispatch outreach via the Poster agent.

        Returns True if outreach was sent successfully.
        This is a no-op if no outreach channel is configured.
        """
        if not proposal.sent_to_email and not proposal.sent_to_linkedin:
            logger.debug(f"Skipping outreach for proposal {proposal.id} — no channel configured")
            return False

        channel = "email" if proposal.sent_to_email else "linkedin"
        target = proposal.sent_to_email or proposal.sent_to_linkedin

        prompt = (
            f"Send the following proposal to {target} via {channel}.\n\n"
            f"Subject: {proposal.title}\n\n"
            f"{proposal.executive_summary or ''}\n\n"
            f"{proposal.call_to_action or ''}"
        )

        wf_result = await self.coordinator.run(
            goal=prompt,
            tenant_id=proposal.tenant_id,
            roles=["poster"],
            pipeline_type="parallel",
        )

        status = wf_result.get("status", "FAILED")
        return status in ("COMPLETED", "SUCCESS")

    # -----------------------------------------------------------------------
    # JSON parsing utilities
    # -----------------------------------------------------------------------

    @staticmethod
    def _parse_json_list(raw: str) -> List[Any]:
        """Extract a JSON array from a string that may contain markdown fences."""
        # Strip markdown code fences
        cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip()
        cleaned = cleaned.rstrip("`").strip()

        # Try direct parse
        try:
            result = json.loads(cleaned)
            if isinstance(result, list):
                return result
            if isinstance(result, dict):
                # Some models wrap the array in a key
                for val in result.values():
                    if isinstance(val, list):
                        return val
        except json.JSONDecodeError:
            pass

        # Try to find a JSON array in the string
        match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return []

    @staticmethod
    def _parse_json_object(raw: str) -> Dict[str, Any]:
        """Extract a JSON object from a string that may contain markdown fences."""
        # Strip markdown code fences
        cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip()
        cleaned = cleaned.rstrip("`").strip()

        # Try direct parse
        try:
            result = json.loads(cleaned)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # Try to find a JSON object in the string
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return {}

    def get_pipeline_summary(self, result: RevenueRunResult) -> Dict[str, Any]:
        """
        Generate a human-readable pipeline summary for reporting.

        Returns a dict suitable for API responses and EventStore events.
        """
        return {
            "run_id": result.run_id,
            "status": result.status,
            "goal": result.goal,
            "metrics": {
                "leads_discovered": result.leads_discovered,
                "leads_qualified": result.leads_qualified,
                "leads_disqualified": result.leads_disqualified,
                "qualification_rate": (
                    round(result.leads_qualified / result.leads_discovered, 2)
                    if result.leads_discovered > 0
                    else 0.0
                ),
                "opportunities_created": result.opportunities_created,
                "proposals_generated": result.proposals_generated,
                "proposals_sent": result.proposals_sent,
                "deals_closed": result.deals_closed,
                "total_pipeline_value_usd": result.total_pipeline_value,
            },
            "top_leads": [
                {
                    "company": lead.company_name,
                    "score": lead.qualification_score,
                    "status": lead.status.value,
                    "industry": lead.industry,
                }
                for lead in sorted(
                    result.leads,
                    key=lambda x: x.qualification_score or 0.0,
                    reverse=True,
                )[:5]
            ],
            "errors": result.errors,
            "started_at": result.started_at.isoformat(),
            "completed_at": (result.completed_at.isoformat() if result.completed_at else None),
        }
