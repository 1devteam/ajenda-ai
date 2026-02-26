"""
Unit tests for compliance module.

Tests all compliance components:
- ComplianceResult
- ComplianceTrace  
- ComplianceEvaluation
- ComplianceRegistry
- ComplianceEngine
- Default rules (ToolPermission, DataAccess, RateLimit)
"""

import pytest
from datetime import datetime
from backend.agents.compliance import (
    ComplianceResult,
    ComplianceTrace,
    ComplianceEvaluation,
    ComplianceRegistry,
    ComplianceEngine,
)
from backend.agents.compliance.rules import (
    ToolPermissionRule,
    DataAccessRule,
    RateLimitRule,
)


class TestComplianceResult:
    """Test ComplianceResult model"""
    
    def test_allow_result(self):
        """Test creating allow result"""
        result = ComplianceResult.allow("test_rule")
        
        assert result.allowed is True
        assert result.reason == ""
        assert result.rule == "test_rule"
    
    def test_block_result(self):
        """Test creating block result"""
        result = ComplianceResult.block(
            rule="test_rule",
            reason="Test reason"
        )
        
        assert result.allowed is False
        assert result.reason == "Test reason"
        assert result.rule == "test_rule"


class TestComplianceTrace:
    """Test ComplianceTrace model"""
    
    def test_trace_creation(self):
        """Test creating compliance trace"""
        trace = ComplianceTrace(
            rule="test_rule",
            allowed=True,
            reason=""
        )
        
        assert trace.rule == "test_rule"
        assert trace.allowed is True
        assert trace.reason == ""
        assert isinstance(trace.timestamp, datetime)
    
    def test_trace_to_dict(self):
        """Test trace serialization"""
        trace = ComplianceTrace(
            rule="test_rule",
            allowed=False,
            reason="Test reason"
        )
        
        data = trace.to_dict()
        
        assert data["rule"] == "test_rule"
        assert data["allowed"] is False
        assert data["reason"] == "Test reason"
        assert "timestamp" in data


class TestComplianceEvaluation:
    """Test ComplianceEvaluation model"""
    
    def test_evaluation_allowed(self):
        """Test allowed evaluation"""
        traces = [
            ComplianceTrace(rule="rule1", allowed=True, reason=""),
            ComplianceTrace(rule="rule2", allowed=True, reason=""),
        ]
        
        evaluation = ComplianceEvaluation(
            allowed=True,
            reason="",
            traces=traces
        )
        
        assert evaluation.allowed is True
        assert evaluation.reason == ""
        assert len(evaluation.traces) == 2
        assert len(evaluation.blocked_by) == 0
        assert len(evaluation.passed_rules) == 2
    
    def test_evaluation_blocked(self):
        """Test blocked evaluation"""
        traces = [
            ComplianceTrace(rule="rule1", allowed=True, reason=""),
            ComplianceTrace(rule="rule2", allowed=False, reason="Blocked"),
        ]
        
        evaluation = ComplianceEvaluation(
            allowed=False,
            reason="Blocked",
            traces=traces
        )
        
        assert evaluation.allowed is False
        assert evaluation.reason == "Blocked"
        assert len(evaluation.blocked_by) == 1
        assert "rule2" in evaluation.blocked_by
        assert len(evaluation.passed_rules) == 1
        assert "rule1" in evaluation.passed_rules
    
    def test_evaluation_to_dict(self):
        """Test evaluation serialization"""
        traces = [
            ComplianceTrace(rule="rule1", allowed=True, reason=""),
        ]
        
        evaluation = ComplianceEvaluation(
            allowed=True,
            reason="",
            traces=traces
        )
        
        data = evaluation.to_dict()
        
        assert data["allowed"] is True
        assert data["reason"] == ""
        assert len(data["traces"]) == 1
        assert "timestamp" in data


class TestComplianceRegistry:
    """Test ComplianceRegistry"""
    
    def setup_method(self):
        """Clear registry before each test"""
        ComplianceRegistry.clear()
    
    def test_register_rule(self):
        """Test registering a rule"""
        ComplianceRegistry.register(ToolPermissionRule)
        
        assert ComplianceRegistry.count() == 1
        assert ComplianceRegistry.is_registered(ToolPermissionRule)
    
    def test_register_duplicate(self):
        """Test registering same rule twice"""
        ComplianceRegistry.register(ToolPermissionRule)
        ComplianceRegistry.register(ToolPermissionRule)
        
        # Should only register once
        assert ComplianceRegistry.count() == 1
    
    def test_get_rules(self):
        """Test getting all rules"""
        ComplianceRegistry.register(ToolPermissionRule)
        ComplianceRegistry.register(DataAccessRule)
        
        rules = ComplianceRegistry.get_rules()
        
        assert len(rules) == 2
        assert ToolPermissionRule in rules
        assert DataAccessRule in rules
    
    def test_get_rule_by_name(self):
        """Test getting rule by name"""
        ComplianceRegistry.register(ToolPermissionRule)
        
        rule_cls = ComplianceRegistry.get_rule_by_name("tool_permission")
        
        assert rule_cls is ToolPermissionRule
    
    def test_get_rule_by_name_not_found(self):
        """Test getting non-existent rule"""
        rule_cls = ComplianceRegistry.get_rule_by_name("nonexistent")
        
        assert rule_cls is None
    
    def test_clear(self):
        """Test clearing registry"""
        ComplianceRegistry.register(ToolPermissionRule)
        ComplianceRegistry.register(DataAccessRule)
        
        assert ComplianceRegistry.count() == 2
        
        ComplianceRegistry.clear()
        
        assert ComplianceRegistry.count() == 0


class TestComplianceEngine:
    """Test ComplianceEngine"""
    
    def setup_method(self):
        """Clear registry before each test"""
        ComplianceRegistry.clear()
    
    def test_engine_auto_register_defaults(self):
        """Test engine auto-registers default rules"""
        engine = ComplianceEngine(auto_register_defaults=True)
        
        # Should have 3 default rules
        assert ComplianceRegistry.count() == 3
    
    def test_engine_no_auto_register(self):
        """Test engine without auto-registration"""
        engine = ComplianceEngine(auto_register_defaults=False)
        
        assert ComplianceRegistry.count() == 0
    
    def test_evaluate_all_pass(self):
        """Test evaluation when all rules pass"""
        ComplianceRegistry.register(ToolPermissionRule)
        engine = ComplianceEngine(auto_register_defaults=False)
        
        context = {
            "agent_type": "researcher",
            "tool_name": "web_search",
        }
        
        evaluation = engine.evaluate("web_search", context)
        
        assert evaluation.allowed is True
        assert len(evaluation.traces) == 1
        assert len(evaluation.passed_rules) == 1
    
    def test_evaluate_blocked(self):
        """Test evaluation when rule blocks"""
        ComplianceRegistry.register(ToolPermissionRule)
        engine = ComplianceEngine(auto_register_defaults=False)
        
        context = {
            "agent_type": "researcher",
            "tool_name": "file_writer",  # Not allowed for researcher
        }
        
        evaluation = engine.evaluate("file_writer", context)
        
        assert evaluation.allowed is False
        assert len(evaluation.blocked_by) == 1
        assert "tool_permission" in evaluation.blocked_by
    
    def test_evaluate_stops_at_first_block(self):
        """Test evaluation stops at first blocking rule"""
        ComplianceRegistry.register(ToolPermissionRule)
        ComplianceRegistry.register(DataAccessRule)
        engine = ComplianceEngine(auto_register_defaults=False)
        
        context = {
            "agent_type": "researcher",
            "tool_name": "file_writer",  # Blocked by ToolPermissionRule
        }
        
        evaluation = engine.evaluate("file_writer", context)
        
        # Should only have 1 trace (stopped at first block)
        assert len(evaluation.traces) == 1
        assert evaluation.traces[0].rule == "tool_permission"


class TestToolPermissionRule:
    """Test ToolPermissionRule"""
    
    def test_researcher_web_search_allowed(self):
        """Test researcher can use web_search"""
        rule = ToolPermissionRule()
        context = {
            "agent_type": "researcher",
            "tool_name": "web_search",
        }
        
        result = rule.check(context)
        
        assert result.allowed is True
    
    def test_researcher_file_writer_blocked(self):
        """Test researcher cannot use file_writer"""
        rule = ToolPermissionRule()
        context = {
            "agent_type": "researcher",
            "tool_name": "file_writer",
        }
        
        result = rule.check(context)
        
        assert result.allowed is False
        assert "not permitted" in result.reason
    
    def test_developer_file_writer_allowed(self):
        """Test developer can use file_writer"""
        rule = ToolPermissionRule()
        context = {
            "agent_type": "developer",
            "tool_name": "file_writer",
        }
        
        result = rule.check(context)
        
        assert result.allowed is True
    
    def test_analyst_python_executor_allowed(self):
        """Test analyst can use python_executor"""
        rule = ToolPermissionRule()
        context = {
            "agent_type": "analyst",
            "tool_name": "python_executor",
        }
        
        result = rule.check(context)
        
        assert result.allowed is True


class TestDataAccessRule:
    """Test DataAccessRule"""
    
    def test_non_data_tool_allowed(self):
        """Test non-data access tools are allowed"""
        rule = DataAccessRule()
        context = {
            "tool_name": "calculator",
        }
        
        result = rule.check(context)
        
        assert result.allowed is True
    
    def test_data_tool_with_justification_allowed(self):
        """Test data access with mission justification"""
        rule = DataAccessRule()
        context = {
            "tool_name": "file_reader",
            "mission_payload": {"task": "analyze logs"},
        }
        
        result = rule.check(context)
        
        assert result.allowed is True
    
    def test_data_tool_without_justification_blocked(self):
        """Test data access without justification"""
        rule = DataAccessRule()
        context = {
            "tool_name": "file_reader",
            "mission_payload": {},
        }
        
        result = rule.check(context)
        
        assert result.allowed is False
        assert "justification" in result.reason


class TestRateLimitRule:
    """Test RateLimitRule"""
    
    def test_non_rate_limited_tool(self):
        """Test non-rate-limited tools are allowed"""
        rule = RateLimitRule()
        context = {
            "agent_id": "agent_123",
            "tool_name": "calculator",
        }
        
        result = rule.check(context)
        
        assert result.allowed is True
    
    def test_rate_limit_under_limit(self):
        """Test usage under rate limit"""
        rule = RateLimitRule()
        context = {
            "agent_id": "agent_123",
            "tool_name": "web_search",
        }
        
        # First 10 calls should pass (limit is 10/min)
        for i in range(10):
            result = rule.check(context)
            assert result.allowed is True
    
    def test_rate_limit_exceeded(self):
        """Test rate limit exceeded"""
        rule = RateLimitRule()
        context = {
            "agent_id": "agent_123",
            "tool_name": "web_search",
        }
        
        # Use up the limit (10/min)
        for i in range(10):
            rule.check(context)
        
        # 11th call should be blocked
        result = rule.check(context)
        
        assert result.allowed is False
        assert "Rate limit exceeded" in result.reason
    
    def test_rate_limit_reset(self):
        """Test rate limit reset"""
        rule = RateLimitRule()
        context = {
            "agent_id": "agent_123",
            "tool_name": "web_search",
        }
        
        # Use up the limit
        for i in range(10):
            rule.check(context)
        
        # Reset
        rule.reset(agent_id="agent_123", tool_name="web_search")
        
        # Should be allowed again
        result = rule.check(context)
        assert result.allowed is True
    
    def test_rate_limit_per_agent(self):
        """Test rate limits are per-agent"""
        rule = RateLimitRule()
        
        # Agent 1 uses up limit
        for i in range(10):
            rule.check({
                "agent_id": "agent_1",
                "tool_name": "web_search",
            })
        
        # Agent 2 should still have quota
        result = rule.check({
            "agent_id": "agent_2",
            "tool_name": "web_search",
        })
        
        assert result.allowed is True


# Integration test
class TestComplianceIntegration:
    """Test full compliance workflow"""
    
    def setup_method(self):
        """Clear registry before each test"""
        ComplianceRegistry.clear()
    
    def test_full_workflow(self):
        """Test complete compliance workflow"""
        # Register all default rules
        ComplianceRegistry.register(ToolPermissionRule)
        ComplianceRegistry.register(DataAccessRule)
        ComplianceRegistry.register(RateLimitRule)
        
        # Create engine
        engine = ComplianceEngine(auto_register_defaults=False)
        
        # Test allowed action
        context = {
            "agent_id": "agent_123",
            "agent_type": "researcher",
            "tenant_id": "tenant_456",
            "tool_name": "web_search",
            "parameters": {"query": "test"},
            "mission_payload": {"task": "research"},
        }
        
        evaluation = engine.evaluate("web_search", context)
        
        assert evaluation.allowed is True
        assert len(evaluation.traces) == 3  # All 3 rules checked
        assert len(evaluation.passed_rules) == 3
        
        # Test blocked action
        context["tool_name"] = "file_writer"
        
        evaluation = engine.evaluate("file_writer", context)
        
        assert evaluation.allowed is False
        assert len(evaluation.blocked_by) == 1
        assert "tool_permission" in evaluation.blocked_by


# Import new rules
from backend.agents.compliance.rules import (
    CostLimitRule,
    DataPrivacyRule,
    ApprovalRequiredRule,
    TenantIsolationRule,
)


class TestCostLimitRule:
    """Test CostLimitRule"""
    
    def test_under_limit(self):
        """Test operation under cost limit"""
        rule = CostLimitRule()
        context = {
            "agent_id": "agent_123",
            "agent_type": "researcher",
            "tool_name": "web_search",
            "estimated_cost_usd": 0.05
        }
        
        result = rule.check(context)
        
        assert result.allowed is True
        assert result.rule == "cost_limit"
    
    def test_exceeds_limit(self):
        """Test operation exceeding cost limit"""
        rule = CostLimitRule()
        context = {
            "agent_id": "agent_123",
            "agent_type": "researcher",
            "tool_name": "web_search",
            "estimated_cost_usd": 5.0
        }
        
        # First two calls allowed (total $10)
        rule.check(context)
        result = rule.check(context)
        assert result.allowed is True
        
        # Third call blocked (would be $15, limit is $10)
        result = rule.check(context)
        assert result.allowed is False
        assert "Cost limit exceeded" in result.reason
        assert result.rule == "cost_limit"
    
    def test_default_cost_estimate(self):
        """Test using default cost estimate"""
        rule = CostLimitRule()
        context = {
            "agent_id": "agent_123",
            "agent_type": "researcher",
            "tool_name": "web_search"
            # No estimated_cost_usd provided
        }
        
        result = rule.check(context)
        
        assert result.allowed is True
        # Should use default $0.05 for web_search
        assert rule.get_cost("agent_123") == 0.05
    
    def test_reset_all(self):
        """Test resetting all cost counters"""
        rule = CostLimitRule()
        context = {
            "agent_id": "agent_123",
            "agent_type": "researcher",
            "tool_name": "web_search",
            "estimated_cost_usd": 5.0
        }
        
        rule.check(context)
        assert rule.get_cost("agent_123") == 5.0
        
        rule.reset()
        assert rule.get_cost("agent_123") == 0.0
    
    def test_reset_specific_agent(self):
        """Test resetting specific agent cost"""
        rule = CostLimitRule()
        
        # Add costs for two agents
        rule.check({
            "agent_id": "agent_123",
            "agent_type": "researcher",
            "tool_name": "web_search",
            "estimated_cost_usd": 5.0
        })
        rule.check({
            "agent_id": "agent_456",
            "agent_type": "analyst",
            "tool_name": "python_executor",
            "estimated_cost_usd": 3.0
        })
        
        # Reset only agent_123
        rule.reset(agent_id="agent_123")
        
        assert rule.get_cost("agent_123") == 0.0
        assert rule.get_cost("agent_456") == 3.0
    
    def test_different_agent_types_different_limits(self):
        """Test different cost limits for different agent types"""
        rule = CostLimitRule()
        
        # Researcher has $10 limit
        researcher_context = {
            "agent_id": "researcher_1",
            "agent_type": "researcher",
            "tool_name": "web_search",
            "estimated_cost_usd": 11.0
        }
        result = rule.check(researcher_context)
        assert result.allowed is False
        
        # Analyst has $20 limit
        analyst_context = {
            "agent_id": "analyst_1",
            "agent_type": "analyst",
            "tool_name": "python_executor",
            "estimated_cost_usd": 15.0
        }
        result = rule.check(analyst_context)
        assert result.allowed is True


class TestDataPrivacyRule:
    """Test DataPrivacyRule"""
    
    def test_no_pii(self):
        """Test parameters without PII"""
        rule = DataPrivacyRule()
        context = {
            "tool_name": "web_search",
            "parameters": {"query": "machine learning"}
        }
        
        result = rule.check(context)
        
        assert result.allowed is True
        assert result.rule == "data_privacy"
    
    def test_email_detected(self):
        """Test email detection"""
        rule = DataPrivacyRule()
        context = {
            "tool_name": "web_search",
            "parameters": {"query": "john.doe@company.com"}
        }
        
        result = rule.check(context)
        
        assert result.allowed is False
        assert "email" in result.reason
        assert result.rule == "data_privacy"
    
    def test_credit_card_detected(self):
        """Test credit card detection"""
        rule = DataPrivacyRule()
        context = {
            "tool_name": "api_caller",
            "parameters": {"card": "4532-1234-5678-9010"}
        }
        
        result = rule.check(context)
        
        assert result.allowed is False
        assert "credit_card" in result.reason
    
    def test_ssn_detected(self):
        """Test SSN detection"""
        rule = DataPrivacyRule()
        context = {
            "tool_name": "database_query",
            "parameters": {"ssn": "123-45-6789"}
        }
        
        result = rule.check(context)
        
        assert result.allowed is False
        assert "ssn" in result.reason
    
    def test_phone_detected(self):
        """Test phone number detection"""
        rule = DataPrivacyRule()
        context = {
            "tool_name": "web_search",
            "parameters": {"query": "Call 555-123-4567"}
        }
        
        result = rule.check(context)
        
        assert result.allowed is False
        assert "phone" in result.reason
    
    def test_api_key_detected(self):
        """Test API key detection"""
        rule = DataPrivacyRule()
        context = {
            "tool_name": "api_caller",
            "parameters": {"key": "sk_live_FAKE1234567890TESTKEY"}
        }
        
        result = rule.check(context)
        
        assert result.allowed is False
        assert "api_key" in result.reason
    
    def test_empty_parameters(self):
        """Test with empty parameters"""
        rule = DataPrivacyRule()
        context = {
            "tool_name": "web_search",
            "parameters": {}
        }
        
        result = rule.check(context)
        
        assert result.allowed is True


class TestApprovalRequiredRule:
    """Test ApprovalRequiredRule"""
    
    def test_tool_not_requiring_approval(self):
        """Test tool that doesn't require approval"""
        rule = ApprovalRequiredRule()
        context = {
            "tool_name": "web_search",
            "parameters": {"query": "test"}
        }
        
        result = rule.check(context)
        
        assert result.allowed is True
        assert result.rule == "approval_required"
    
    def test_file_writer_requires_approval(self):
        """Test file_writer requires approval"""
        rule = ApprovalRequiredRule()
        context = {
            "tool_name": "file_writer",
            "parameters": {"path": "/tmp/test.txt"}
        }
        
        result = rule.check(context)
        
        assert result.allowed is False
        assert "requires approval" in result.reason
        assert result.rule == "approval_required"
    
    def test_database_query_requires_approval(self):
        """Test database_query requires approval"""
        rule = ApprovalRequiredRule()
        context = {
            "tool_name": "database_query",
            "parameters": {"query": "SELECT * FROM users"}
        }
        
        result = rule.check(context)
        
        assert result.allowed is False
        assert "requires approval" in result.reason
    
    def test_sensitive_path_requires_approval(self):
        """Test sensitive path requires approval"""
        rule = ApprovalRequiredRule()
        context = {
            "tool_name": "file_writer",
            "parameters": {"path": "/prod/config.yaml"}
        }
        
        result = rule.check(context)
        
        assert result.allowed is False
        assert "Sensitive path" in result.reason
        assert "/prod/config.yaml" in result.reason
    
    def test_env_file_requires_approval(self):
        """Test .env file requires approval"""
        rule = ApprovalRequiredRule()
        context = {
            "tool_name": "file_writer",
            "parameters": {"path": "/app/.env"}
        }
        
        result = rule.check(context)
        
        assert result.allowed is False
        assert "Sensitive path" in result.reason


class TestTenantIsolationRule:
    """Test TenantIsolationRule"""
    
    def test_tool_not_tenant_scoped(self):
        """Test tool that doesn't access tenant data"""
        rule = TenantIsolationRule()
        context = {
            "tenant_id": "tenant_456",
            "tool_name": "web_search",
            "parameters": {"query": "test"}
        }
        
        result = rule.check(context)
        
        assert result.allowed is True
        assert result.rule == "tenant_isolation"
    
    def test_same_tenant_access(self):
        """Test accessing same tenant data"""
        rule = TenantIsolationRule()
        context = {
            "tenant_id": "tenant_456",
            "tool_name": "file_reader",
            "parameters": {"path": "/tenant_456/data.json"}
        }
        
        result = rule.check(context)
        
        assert result.allowed is True
    
    def test_cross_tenant_access_blocked(self):
        """Test cross-tenant access is blocked"""
        rule = TenantIsolationRule()
        context = {
            "tenant_id": "tenant_456",
            "tool_name": "file_reader",
            "parameters": {"path": "/tenant_789/data.json"}
        }
        
        result = rule.check(context)
        
        assert result.allowed is False
        assert "Cross-tenant access denied" in result.reason
        assert "tenant_456" in result.reason
        assert "tenant_789" in result.reason
        assert result.rule == "tenant_isolation"
    
    def test_cross_tenant_query_blocked(self):
        """Test cross-tenant database query is blocked"""
        rule = TenantIsolationRule()
        context = {
            "tenant_id": "tenant_456",
            "tool_name": "database_query",
            "parameters": {"query": "SELECT * FROM data WHERE tenant_id='tenant_789'"}
        }
        
        result = rule.check(context)
        
        assert result.allowed is False
        assert "Cross-tenant query detected" in result.reason
    
    def test_same_tenant_query_allowed(self):
        """Test same-tenant database query is allowed"""
        rule = TenantIsolationRule()
        context = {
            "tenant_id": "tenant_456",
            "tool_name": "database_query",
            "parameters": {"query": "SELECT * FROM data WHERE tenant_id='tenant_456'"}
        }
        
        result = rule.check(context)
        
        assert result.allowed is True
    
    def test_path_without_tenant_id(self):
        """Test path without tenant ID is allowed"""
        rule = TenantIsolationRule()
        context = {
            "tenant_id": "tenant_456",
            "tool_name": "file_reader",
            "parameters": {"path": "/shared/public/data.json"}
        }
        
        result = rule.check(context)
        
        assert result.allowed is True
