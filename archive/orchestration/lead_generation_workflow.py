"""
Lead Generation Workflow for Omnipath v2 — Phase 3 (v6.2)

Orchestrates a structured multi-step workflow for finding and qualifying
business leads using web search, optional browser automation, and LLM analysis.

Workflow steps:
    1. Search — DuckDuckGo search for target companies/contacts.
    2. Enrich  — Optional browser visit to each result URL for deeper data.
    3. Analyse — LLM scores and qualifies each lead against criteria.
    4. Report  — Returns structured list of qualified leads with scores.

Usage::

    workflow = LeadGenerationWorkflow(
        llm_service=llm_service,
        tool_bridge=mcp_bridge,
    )
    result = await workflow.run(
        query="retail loss prevention companies USA",
        criteria="Looking for mid-market retailers with 50+ locations",
        max_leads=10,
        enrich=False,
    )

Built with Pride for Obex Blackvault
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.core.logging_config import get_logger
from backend.integrations.mcp.tool_bridge import MCPToolBridge

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Lead:
    """A qualified business lead."""

    name: str
    url: str
    snippet: str
    score: float = 0.0  # 0.0 – 1.0 qualification score
    reasoning: str = ""
    enriched_text: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LeadGenerationResult:
    """Result of a lead generation workflow run."""

    query: str
    criteria: str
    leads: List[Lead]
    total_found: int
    total_qualified: int
    workflow_steps: List[str]
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict for API responses / EventStore."""
        return {
            "query": self.query,
            "criteria": self.criteria,
            "total_found": self.total_found,
            "total_qualified": self.total_qualified,
            "workflow_steps": self.workflow_steps,
            "error": self.error,
            "leads": [
                {
                    "name": lead.name,
                    "url": lead.url,
                    "snippet": lead.snippet,
                    "score": lead.score,
                    "reasoning": lead.reasoning,
                }
                for lead in self.leads
            ],
        }


# ---------------------------------------------------------------------------
# LeadGenerationWorkflow
# ---------------------------------------------------------------------------


class LeadGenerationWorkflow:
    """
    Structured lead generation workflow.

    Args:
        llm_service:  LLMService instance for qualification analysis.
        tool_bridge:  MCPToolBridge for web_search and browser tool access.
        tenant_id:    Tenant ID for LLM routing (optional).
    """

    QUALIFICATION_PROMPT = """You are a lead qualification specialist.

Given a business lead and qualification criteria, score the lead from 0.0 to 1.0
and explain your reasoning in one sentence.

Criteria: {criteria}

Lead:
  Name: {name}
  URL: {url}
  Description: {description}

Respond with ONLY valid JSON in this exact format:
{{"score": 0.85, "reasoning": "One sentence explanation."}}"""

    def __init__(
        self,
        llm_service: Any,
        tool_bridge: MCPToolBridge,
        tenant_id: Optional[str] = None,
    ) -> None:
        self._llm = llm_service
        self._bridge = tool_bridge
        self._tenant_id = tenant_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        query: str,
        criteria: str,
        max_leads: int = 10,
        enrich: bool = False,
        min_score: float = 0.5,
    ) -> LeadGenerationResult:
        """
        Execute the lead generation workflow.

        Args:
            query:     Search query for finding leads (e.g. "retail loss prevention USA").
            criteria:  Qualification criteria for the LLM scorer.
            max_leads: Maximum number of leads to return (default 10).
            enrich:    Whether to visit each lead URL for deeper text extraction.
            min_score: Minimum qualification score to include in results (default 0.5).

        Returns:
            LeadGenerationResult with qualified leads and workflow metadata.
        """
        steps: List[str] = []
        logger.info(f"LeadGenerationWorkflow: starting — query='{query}', max_leads={max_leads}")

        # Step 1: Search
        steps.append("web_search")
        raw_results = await self._search(query, max_leads * 2)
        if not raw_results:
            return LeadGenerationResult(
                query=query,
                criteria=criteria,
                leads=[],
                total_found=0,
                total_qualified=0,
                workflow_steps=steps,
                error="Web search returned no results.",
            )

        logger.info(f"LeadGenerationWorkflow: found {len(raw_results)} raw results")

        # Step 2: Optional enrichment
        if enrich and self._bridge.has_tool("browser"):
            steps.append("browser_enrich")
            raw_results = await self._enrich(raw_results)

        # Step 3: LLM qualification
        steps.append("llm_qualify")
        leads = await self._qualify_all(raw_results, criteria, min_score)

        # Sort by score descending, cap at max_leads
        leads.sort(key=lambda lead: lead.score, reverse=True)
        leads = leads[:max_leads]

        qualified = [lead for lead in leads if lead.score >= min_score]

        logger.info(
            f"LeadGenerationWorkflow: complete — "
            f"{len(raw_results)} found, {len(qualified)} qualified"
        )

        return LeadGenerationResult(
            query=query,
            criteria=criteria,
            leads=leads,
            total_found=len(raw_results),
            total_qualified=len(qualified),
            workflow_steps=steps,
        )

    # ------------------------------------------------------------------
    # Step 1: Search
    # ------------------------------------------------------------------

    async def _search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Run web_search and return raw result list."""
        try:
            raw = await self._bridge.call_tool(
                "web_search",
                {"query": query, "max_results": max_results},
            )
            data = json.loads(raw) if isinstance(raw, str) else raw
            return data.get("results", [])
        except Exception as exc:
            logger.error(f"LeadGenerationWorkflow._search failed: {exc}", exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Step 2: Enrich
    # ------------------------------------------------------------------

    async def _enrich(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Visit each result URL and extract page text."""
        enriched = []
        tasks = [self._enrich_one(r) for r in results]
        enriched = await asyncio.gather(*tasks, return_exceptions=True)
        # Filter out exceptions
        return [r for r in enriched if isinstance(r, dict)]

    async def _enrich_one(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Enrich a single result with browser-extracted text."""
        url = result.get("url", "")
        if not url:
            return result

        try:
            # Navigate
            await self._bridge.call_tool("browser", {"action": "navigate", "url": url})
            # Extract text
            raw = await self._bridge.call_tool("browser", {"action": "get_text"})
            data = json.loads(raw) if isinstance(raw, str) else raw
            result["enriched_text"] = data.get("text", "")[:3_000]
        except Exception as exc:
            logger.warning(f"LeadGenerationWorkflow: enrichment failed for {url}: {exc}")

        return result

    # ------------------------------------------------------------------
    # Step 3: Qualify
    # ------------------------------------------------------------------

    async def _qualify_all(
        self,
        results: List[Dict[str, Any]],
        criteria: str,
        min_score: float,
    ) -> List[Lead]:
        """Qualify all results concurrently."""
        tasks = [self._qualify_one(r, criteria) for r in results]
        qualified = await asyncio.gather(*tasks, return_exceptions=True)
        return [item for item in qualified if isinstance(item, Lead)]

    async def _qualify_one(self, result: Dict[str, Any], criteria: str) -> Lead:
        """Use LLM to score a single lead."""
        name = result.get("title", "Unknown")
        url = result.get("url", "")
        description = result.get("enriched_text") or result.get("snippet", "")

        lead = Lead(
            name=name,
            url=url,
            snippet=result.get("snippet", ""),
            enriched_text=result.get("enriched_text", ""),
        )

        prompt = self.QUALIFICATION_PROMPT.format(
            criteria=criteria,
            name=name,
            url=url,
            description=description[:1_500],
        )

        try:
            llm = self._llm.get_llm("worker", self._tenant_id)
            response = await llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)

            # Parse JSON response
            parsed = json.loads(content.strip())
            lead.score = float(parsed.get("score", 0.0))
            lead.reasoning = str(parsed.get("reasoning", ""))

        except json.JSONDecodeError:
            # LLM didn't return valid JSON — assign neutral score
            lead.score = 0.3
            lead.reasoning = "Could not parse LLM qualification response."
        except Exception as exc:
            logger.warning(f"LeadGenerationWorkflow: qualification failed for {name}: {exc}")
            lead.score = 0.0
            lead.reasoning = f"Qualification error: {exc}"

        return lead
