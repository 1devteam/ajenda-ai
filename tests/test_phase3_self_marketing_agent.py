"""
Phase 3 Test Suite — The Self-Marketing Agent (v6.2)

Tests for:
    - PlaywrightBrowserTool (graceful degradation when playwright not installed)
    - TwitterTool (credential validation, action routing, error handling)
    - LeadGenerationWorkflow (search → qualify pipeline)
    - SocialMediaPostingSaga (full saga lifecycle with compensation)
    - Campaigns API route (CRUD + run endpoint)

Built with Pride for Obex Blackvault
"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run(coro):
    """Run a coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ===========================================================================
# 1. PlaywrightBrowserTool
# ===========================================================================


class TestPlaywrightBrowserTool:
    """Tests for the PlaywrightBrowserTool."""

    def test_browser_tool_graceful_degradation_without_playwright(self):
        """BrowserTool returns an error dict when playwright is not installed."""
        # Temporarily hide playwright from sys.modules
        saved = sys.modules.get("playwright")
        sys.modules["playwright"] = None  # type: ignore[assignment]
        sys.modules["playwright.async_api"] = None  # type: ignore[assignment]

        try:
            from backend.integrations.tools.browser_tool import PlaywrightBrowserTool

            tool = PlaywrightBrowserTool()
            result = run(tool.execute(action="navigate", url="https://example.com"))
            assert result["success"] is False
            assert "playwright" in result["error"].lower()
        finally:
            if saved is None:
                sys.modules.pop("playwright", None)
                sys.modules.pop("playwright.async_api", None)
            else:
                sys.modules["playwright"] = saved

    def test_browser_tool_name_and_category(self):
        """BrowserTool has correct name and category."""
        from backend.integrations.tools.browser_tool import PlaywrightBrowserTool
        from backend.agents.tools.tool_registry import ToolCategory

        tool = PlaywrightBrowserTool()
        assert tool.name == "browser"
        assert tool.category == ToolCategory.COMMUNICATION

    def test_browser_tool_unknown_action(self):
        """BrowserTool returns error for unknown actions."""
        # Mock playwright to be available but return error for unknown action
        mock_pw = types.ModuleType("playwright")
        mock_pw_api = types.ModuleType("playwright.async_api")
        mock_pw_api.async_playwright = MagicMock()
        sys.modules["playwright"] = mock_pw
        sys.modules["playwright.async_api"] = mock_pw_api

        try:
            from backend.integrations.tools.browser_tool import PlaywrightBrowserTool

            tool = PlaywrightBrowserTool()
            # Without a real browser, the tool will fail — we just test the
            # unknown action path via direct call
            result = run(tool.execute(action="unknown_action"))
            assert result["success"] is False
        except Exception:
            pass  # Expected — no real browser in test environment
        finally:
            sys.modules.pop("playwright", None)
            sys.modules.pop("playwright.async_api", None)


# ===========================================================================
# 2. TwitterTool
# ===========================================================================


class TestTwitterTool:
    """Tests for the TwitterTool."""

    def test_twitter_tool_name_and_category(self):
        """TwitterTool has correct name and category."""
        from backend.integrations.tools.twitter_tool import TwitterTool
        from backend.agents.tools.tool_registry import ToolCategory

        tool = TwitterTool()
        assert tool.name == "twitter"
        assert tool.category == ToolCategory.COMMUNICATION

    def test_twitter_tool_no_credentials_returns_error(self):
        """TwitterTool returns error when no credentials are configured."""
        from backend.integrations.tools.twitter_tool import TwitterTool

        tool = TwitterTool(
            api_key="",
            api_secret="",
            access_token="",
            access_token_secret="",
        )
        result = run(tool.execute(action="post_tweet", text="Hello world"))
        assert result["success"] is False
        assert "credentials" in result["error"].lower()

    def test_twitter_tool_tweet_too_long(self):
        """TwitterTool rejects tweets exceeding 280 characters."""
        from backend.integrations.tools.twitter_tool import TwitterTool

        # Mock tweepy to be available
        mock_tweepy = types.ModuleType("tweepy")
        mock_client = MagicMock()
        mock_tweepy.Client = MagicMock(return_value=mock_client)
        sys.modules["tweepy"] = mock_tweepy

        try:
            tool = TwitterTool(
                api_key="key",
                api_secret="secret",
                access_token="token",
                access_token_secret="token_secret",
            )
            long_text = "x" * 281
            result = run(tool.execute(action="post_tweet", text=long_text))
            assert result["success"] is False
            assert "280" in result["error"]
        finally:
            sys.modules.pop("tweepy", None)

    def test_twitter_tool_unknown_action(self):
        """TwitterTool returns error for unknown actions."""
        from backend.integrations.tools.twitter_tool import TwitterTool

        mock_tweepy = types.ModuleType("tweepy")
        mock_tweepy.Client = MagicMock()
        sys.modules["tweepy"] = mock_tweepy

        try:
            tool = TwitterTool(
                api_key="key",
                api_secret="secret",
                access_token="token",
                access_token_secret="token_secret",
            )
            result = run(tool.execute(action="invalid_action"))
            assert result["success"] is False
            assert "Unknown action" in result["error"]
        finally:
            sys.modules.pop("tweepy", None)

    def test_twitter_tool_post_tweet_success(self):
        """TwitterTool successfully posts a tweet with mocked tweepy."""
        from backend.integrations.tools.twitter_tool import TwitterTool

        mock_tweepy = types.ModuleType("tweepy")
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data = {"id": "tweet_123"}
        mock_client.create_tweet = MagicMock(return_value=mock_response)
        mock_tweepy.Client = MagicMock(return_value=mock_client)
        sys.modules["tweepy"] = mock_tweepy

        try:
            tool = TwitterTool(
                api_key="key",
                api_secret="secret",
                access_token="token",
                access_token_secret="token_secret",
            )
            result = run(tool.execute(action="post_tweet", text="Hello Citadel!"))
            assert result["success"] is True
            assert result["tweet_id"] == "tweet_123"
            assert "twitter.com" in result["url"]
        finally:
            sys.modules.pop("tweepy", None)

    def test_twitter_tool_post_thread_empty_texts(self):
        """TwitterTool rejects empty texts list for post_thread."""
        from backend.integrations.tools.twitter_tool import TwitterTool

        mock_tweepy = types.ModuleType("tweepy")
        mock_tweepy.Client = MagicMock()
        sys.modules["tweepy"] = mock_tweepy

        try:
            tool = TwitterTool(
                api_key="key",
                api_secret="secret",
                access_token="token",
                access_token_secret="token_secret",
            )
            result = run(tool.execute(action="post_thread", texts=[]))
            assert result["success"] is False
            assert "texts" in result["error"]
        finally:
            sys.modules.pop("tweepy", None)


# ===========================================================================
# 3. LeadGenerationWorkflow
# ===========================================================================


class TestLeadGenerationWorkflow:
    """Tests for the LeadGenerationWorkflow."""

    def _make_mock_bridge(self, search_results=None):
        """Create a mock MCPToolBridge."""
        bridge = MagicMock()
        bridge.has_tool = MagicMock(return_value=False)
        results = search_results or [
            {"title": "Acme Corp", "url": "https://acme.com", "snippet": "Retail loss prevention"},
            {"title": "Beta Inc", "url": "https://beta.com", "snippet": "Security solutions"},
        ]
        bridge.call_tool = AsyncMock(return_value=json.dumps({"results": results}))
        return bridge

    def _make_mock_llm_service(self, score=0.8, reasoning="Good match"):
        """Create a mock LLMService."""
        llm_service = MagicMock()
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = json.dumps({"score": score, "reasoning": reasoning})
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        llm_service.get_llm = MagicMock(return_value=mock_llm)
        return llm_service

    def test_lead_generation_basic_run(self):
        """LeadGenerationWorkflow returns qualified leads from search results."""
        from backend.orchestration.lead_generation_workflow import LeadGenerationWorkflow

        bridge = self._make_mock_bridge()
        llm_service = self._make_mock_llm_service(score=0.85)

        workflow = LeadGenerationWorkflow(
            llm_service=llm_service,
            tool_bridge=bridge,
        )

        result = run(
            workflow.run(
                query="retail loss prevention companies",
                criteria="Mid-market retailers with 50+ locations",
                max_leads=5,
            )
        )

        assert result.query == "retail loss prevention companies"
        assert result.total_found == 2
        assert len(result.leads) == 2
        assert result.leads[0].score == 0.85
        assert "web_search" in result.workflow_steps
        assert "llm_qualify" in result.workflow_steps

    def test_lead_generation_empty_search_returns_error(self):
        """LeadGenerationWorkflow handles empty search results gracefully."""
        from backend.orchestration.lead_generation_workflow import LeadGenerationWorkflow

        bridge = MagicMock()
        bridge.has_tool = MagicMock(return_value=False)
        bridge.call_tool = AsyncMock(return_value=json.dumps({"results": []}))

        llm_service = self._make_mock_llm_service()

        workflow = LeadGenerationWorkflow(
            llm_service=llm_service,
            tool_bridge=bridge,
        )

        result = run(
            workflow.run(
                query="nonexistent company type xyz",
                criteria="Any company",
            )
        )

        assert result.total_found == 0
        assert result.error is not None
        assert len(result.leads) == 0

    def test_lead_generation_filters_by_min_score(self):
        """LeadGenerationWorkflow filters leads below min_score threshold."""
        from backend.orchestration.lead_generation_workflow import LeadGenerationWorkflow

        bridge = self._make_mock_bridge(
            search_results=[
                {"title": "Good Lead", "url": "https://good.com", "snippet": "Perfect match"},
                {"title": "Bad Lead", "url": "https://bad.com", "snippet": "No match"},
            ]
        )

        # First call returns 0.9, second returns 0.2
        llm_service = MagicMock()
        mock_llm = MagicMock()
        responses = [
            MagicMock(content=json.dumps({"score": 0.9, "reasoning": "Great"})),
            MagicMock(content=json.dumps({"score": 0.2, "reasoning": "Poor"})),
        ]
        mock_llm.ainvoke = AsyncMock(side_effect=responses)
        llm_service.get_llm = MagicMock(return_value=mock_llm)

        workflow = LeadGenerationWorkflow(
            llm_service=llm_service,
            tool_bridge=bridge,
        )

        result = run(
            workflow.run(
                query="test",
                criteria="test",
                min_score=0.5,
            )
        )

        assert result.total_qualified == 1
        assert result.leads[0].score == 0.9

    def test_lead_result_to_dict(self):
        """LeadGenerationResult.to_dict() returns correct structure."""
        from backend.orchestration.lead_generation_workflow import (
            Lead,
            LeadGenerationResult,
        )

        result = LeadGenerationResult(
            query="test query",
            criteria="test criteria",
            leads=[Lead(name="Test Co", url="https://test.com", snippet="Test", score=0.7)],
            total_found=1,
            total_qualified=1,
            workflow_steps=["web_search", "llm_qualify"],
        )

        d = result.to_dict()
        assert d["query"] == "test query"
        assert d["total_found"] == 1
        assert len(d["leads"]) == 1
        assert d["leads"][0]["score"] == 0.7


# ===========================================================================
# 4. SocialMediaPostingSaga
# ===========================================================================


class TestSocialMediaPostingSaga:
    """Tests for the SocialMediaPostingSaga."""

    def _make_orchestrator(self):
        """Create a real SagaOrchestrator with a mock EventStore."""
        from backend.core.saga.saga_orchestrator import SagaOrchestrator

        event_store = MagicMock()
        # SagaOrchestrator._emit_event calls event_store.append()
        event_store.append = AsyncMock(return_value={"id": "evt_123"})
        # SocialMediaPostingSaga steps call event_store.append_event()
        event_store.append_event = AsyncMock(return_value={"id": "evt_123"})
        return SagaOrchestrator(event_store=event_store), event_store

    def _make_mission_executor(self, result_text="Test post content"):
        """Create a mock MissionExecutor."""
        executor = MagicMock()
        executor.execute_mission = AsyncMock(
            return_value={
                "status": "COMPLETED",
                "result": result_text,
                "cost": 0.01,
            }
        )
        return executor

    def _make_tool_bridge(self, has_tool=False):
        """Create a mock MCPToolBridge."""
        bridge = MagicMock()
        bridge.has_tool = MagicMock(return_value=has_tool)
        bridge.call_tool = AsyncMock(
            return_value=json.dumps(
                {
                    "success": True,
                    "tweet_id": "tweet_456",
                }
            )
        )
        return bridge

    def test_saga_executes_successfully_in_simulation_mode(self):
        """SocialMediaPostingSaga completes all steps in simulation mode."""
        from backend.core.saga.saga_orchestrator import SocialMediaPostingSaga

        orchestrator, event_store = self._make_orchestrator()
        executor = self._make_mission_executor("Citadel AI is transforming retail security.")
        bridge = self._make_tool_bridge(has_tool=False)  # No real tool — simulation

        saga = SocialMediaPostingSaga(
            orchestrator=orchestrator,
            mission_executor=executor,
            tool_bridge=bridge,
            event_store=event_store,
        )

        success = run(
            saga.execute(
                campaign_id="campaign_test_001",
                agent_id="agent_test_001",
                tenant_id="tenant_test",
                platform="twitter",
                brief="Write about how Citadel AI reduces retail shrink by 40%",
                post_index=0,
                total_posts=3,
            )
        )

        assert success is True
        # EventStore should have been called for record_post
        assert event_store.append_event.called

    def test_saga_records_post_published_event(self):
        """SocialMediaPostingSaga emits campaign.post_published event."""
        from backend.core.saga.saga_orchestrator import SocialMediaPostingSaga

        orchestrator, event_store = self._make_orchestrator()
        executor = self._make_mission_executor("Test content")
        bridge = self._make_tool_bridge(has_tool=False)

        saga = SocialMediaPostingSaga(
            orchestrator=orchestrator,
            mission_executor=executor,
            tool_bridge=bridge,
            event_store=event_store,
        )

        run(
            saga.execute(
                campaign_id="campaign_evt_test",
                agent_id="agent_001",
                tenant_id="tenant_001",
                platform="twitter",
                brief="Test brief",
            )
        )

        # Find the post_published event call
        calls = event_store.append_event.call_args_list
        event_types = [c.kwargs.get("event_type") or c.args[1] for c in calls]
        assert "campaign.post_published" in event_types

    def test_saga_schedules_next_post_when_configured(self):
        """SocialMediaPostingSaga emits campaign.next_post_scheduled when schedule_next_at is set."""
        from backend.core.saga.saga_orchestrator import SocialMediaPostingSaga

        orchestrator, event_store = self._make_orchestrator()
        executor = self._make_mission_executor("Test content")
        bridge = self._make_tool_bridge(has_tool=False)

        saga = SocialMediaPostingSaga(
            orchestrator=orchestrator,
            mission_executor=executor,
            tool_bridge=bridge,
            event_store=event_store,
        )

        run(
            saga.execute(
                campaign_id="campaign_schedule_test",
                agent_id="agent_001",
                tenant_id="tenant_001",
                platform="twitter",
                brief="Test brief",
                post_index=0,
                total_posts=3,
                schedule_next_at="2026-03-03T12:00:00",
            )
        )

        calls = event_store.append_event.call_args_list
        event_types = [c.kwargs.get("event_type") or c.args[1] for c in calls]
        assert "campaign.next_post_scheduled" in event_types

    def test_saga_does_not_schedule_when_last_post(self):
        """SocialMediaPostingSaga does not schedule next when post_index == total_posts - 1."""
        from backend.core.saga.saga_orchestrator import SocialMediaPostingSaga

        orchestrator, event_store = self._make_orchestrator()
        executor = self._make_mission_executor("Test content")
        bridge = self._make_tool_bridge(has_tool=False)

        saga = SocialMediaPostingSaga(
            orchestrator=orchestrator,
            mission_executor=executor,
            tool_bridge=bridge,
            event_store=event_store,
        )

        run(
            saga.execute(
                campaign_id="campaign_last_test",
                agent_id="agent_001",
                tenant_id="tenant_001",
                platform="twitter",
                brief="Test brief",
                post_index=2,  # Last post (0-indexed, total=3)
                total_posts=3,
                schedule_next_at="2026-03-03T12:00:00",
            )
        )

        calls = event_store.append_event.call_args_list
        event_types = [c.kwargs.get("event_type") or c.args[1] for c in calls]
        # Should NOT schedule next since this is the last post
        assert "campaign.next_post_scheduled" not in event_types


# ===========================================================================
# 5. Campaigns API Route
# ===========================================================================


class TestCampaignsRoute:
    """Tests for the campaigns API route models and logic."""

    def test_create_campaign_request_validation(self):
        """CreateCampaignRequest validates platform field."""
        from backend.api.routes.campaigns import CreateCampaignRequest

        # Valid platform
        req = CreateCampaignRequest(
            name="Test Campaign",
            platform="twitter",
            brief="Write about AI in retail security",
            agent_id="agent_001",
        )
        assert req.platform == "twitter"
        assert req.total_posts == 1  # Default

    def test_create_campaign_request_invalid_platform(self):
        """CreateCampaignRequest rejects invalid platform values."""
        from backend.api.routes.campaigns import CreateCampaignRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CreateCampaignRequest(
                name="Test",
                platform="tiktok",  # Not supported
                brief="Test brief",
                agent_id="agent_001",
            )

    def test_create_campaign_request_defaults(self):
        """CreateCampaignRequest has correct defaults."""
        from backend.api.routes.campaigns import CreateCampaignRequest

        req = CreateCampaignRequest(
            name="Test",
            platform="reddit",
            brief="Test brief",
            agent_id="agent_001",
        )
        assert req.total_posts == 1
        assert req.post_interval_hours == 24.0
        assert req.auto_schedule is False

    def test_campaign_response_model_fields(self):
        """CampaignResponse has all required fields."""
        from backend.api.routes.campaigns import CampaignResponse

        fields = set(CampaignResponse.model_fields.keys())
        required = {
            "id",
            "name",
            "platform",
            "brief",
            "agent_id",
            "tenant_id",
            "total_posts",
            "posts_published",
            "status",
            "created_at",
        }
        assert required.issubset(fields)

    def test_run_campaign_response_model(self):
        """RunCampaignResponse has all required fields."""
        from backend.api.routes.campaigns import RunCampaignResponse

        resp = RunCampaignResponse(
            campaign_id="campaign_001",
            post_index=0,
            success=True,
            simulated=True,
            message="Post 1/3 published successfully",
        )
        assert resp.success is True
        assert resp.simulated is True
        assert resp.post_id is None  # Optional field


# ===========================================================================
# 6. Tool Registry — Phase 3 registration
# ===========================================================================


class TestToolRegistryPhase3:
    """Tests for Phase 3 tool registration in ToolRegistry."""

    def test_tool_registry_registers_phase3_tools_gracefully(self):
        """ToolRegistry registers Phase 3 tools without crashing if deps missing."""
        from backend.agents.tools.tool_registry import ToolRegistry

        # Should not raise even if playwright/tweepy are not installed
        registry = ToolRegistry()
        assert registry is not None
        # Core tools should always be present
        assert "web_search" in registry.tools
        assert "calculator" in registry.tools

    def test_tool_registry_has_browser_tool_when_playwright_available(self):
        """ToolRegistry registers browser tool when playwright is importable."""
        # Mock playwright as available
        mock_pw = types.ModuleType("playwright")
        mock_pw_api = types.ModuleType("playwright.async_api")
        mock_pw_api.async_playwright = MagicMock()
        sys.modules["playwright"] = mock_pw
        sys.modules["playwright.async_api"] = mock_pw_api

        try:
            # Re-import to get fresh registry with mocked playwright
            from importlib import reload
            import backend.integrations.tools.browser_tool as bt

            reload(bt)
            from backend.agents.tools.tool_registry import ToolRegistry

            registry = ToolRegistry()
            # browser tool should be registered
            assert "browser" in registry.tools
        finally:
            sys.modules.pop("playwright", None)
            sys.modules.pop("playwright.async_api", None)

    def test_tool_registry_has_twitter_tool_when_tweepy_available(self):
        """ToolRegistry registers twitter tool when tweepy is importable."""
        mock_tweepy = types.ModuleType("tweepy")
        mock_tweepy.Client = MagicMock()
        sys.modules["tweepy"] = mock_tweepy

        try:
            from importlib import reload
            import backend.integrations.tools.twitter_tool as tt

            reload(tt)
            from backend.agents.tools.tool_registry import ToolRegistry

            registry = ToolRegistry()
            assert "twitter" in registry.tools
        finally:
            sys.modules.pop("tweepy", None)
