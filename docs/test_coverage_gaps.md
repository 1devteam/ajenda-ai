# Test Coverage Gap Report

**Generated**: 2026-03-03 07:21 UTC
**Total untested files**: 96
**Total backend files scanned**: 141

---

## Summary by Priority

| Priority | Threshold | Count |
|---|---|---|
| **Critical** | ≥ 400 lines | 38 |
| **High** | 200–399 lines | 34 |
| **Medium** | 50–199 lines | 21 |
| **Low** | < 50 lines | 3 |

## Critical Priority (≥ 400 lines)

| File | Lines | Suggested Test File |
|---|---|---|
| `backend/core/saga/saga_orchestrator.py` | 1627 | `tests/test_saga_orchestrator.py` |
| `backend/core/cqrs/cqrs_impl.py` | 916 | `tests/test_cqrs_impl.py` |
| `backend/api/routes/agents.py` | 907 | `tests/test_agents.py` |
| `backend/api/routes/missions.py` | 820 | `tests/test_missions.py` |
| `backend/agents/compliance/rules.py` | 756 | `tests/test_rules.py` |
| `backend/orchestration/mission_executor.py` | 741 | `tests/test_mission_executor.py` |
| `backend/orchestration/workforce_coordinator.py` | 707 | `tests/test_workforce_coordinator.py` |
| `backend/orchestration/revenue_agent.py` | 696 | `tests/test_revenue_agent.py` |
| `backend/agents/integration/nats_governance.py` | 687 | `tests/test_nats_governance.py` |
| `backend/api/routes/tags.py` | 644 | `tests/test_tags.py` |
| `backend/api/routes/revenue.py` | 642 | `tests/test_revenue.py` |
| `backend/api/routes/risk.py` | 632 | `tests/test_risk.py` |
| `backend/core/scheduler/scheduler_service.py` | 612 | `tests/test_scheduler_service.py` |
| `backend/core/event_sourcing/event_store_impl.py` | 604 | `tests/test_event_store_impl.py` |
| `backend/main.py` | 596 | `tests/test_main.py` |
| `backend/database/models.py` | 567 | `tests/test_models.py` |
| `backend/api/routes/policies.py` | 550 | `tests/test_policies.py` |
| `backend/integrations/mcp/mcp_client.py` | 546 | `tests/test_mcp_client.py` |
| `backend/database/governance_models.py` | 545 | `tests/test_governance_models.py` |
| `backend/economy/resource_marketplace.py` | 545 | `tests/test_resource_marketplace.py` |
| `backend/agents/integration/governance_hooks.py` | 538 | `tests/test_governance_hooks.py` |
| `backend/api/routes/integrations.py` | 531 | `tests/test_integrations.py` |
| `backend/api/routes/workforces.py` | 515 | `tests/test_workforces.py` |
| `backend/core/event_sourcing/projections.py` | 507 | `tests/test_projections.py` |
| `backend/meta_learning/adaptive_engine.py` | 489 | `tests/test_adaptive_engine.py` |
| `backend/agents/implementations/researcher_agent.py` | 484 | `tests/test_researcher_agent.py` |
| `backend/agents/tools/tool_registry.py` | 467 | `tests/test_tool_registry.py` |
| `backend/api/routes/auth.py` | 451 | `tests/test_auth.py` |
| `backend/api/routes/registry.py` | 449 | `tests/test_registry.py` |
| `backend/api/routes/scheduler.py` | 449 | `tests/test_scheduler.py` |
| `backend/database/repositories/asset_repository.py` | 445 | `tests/test_asset_repository.py` |
| `backend/database/repositories/audit_repository.py` | 441 | `tests/test_audit_repository.py` |
| `backend/api/routes/audit.py` | 438 | `tests/test_audit.py` |
| `backend/agents/compliance/policy.py` | 435 | `tests/test_policy.py` |
| `backend/api/routes/dashboard.py` | 432 | `tests/test_dashboard.py` |
| `backend/core/event_bus/nats_bus.py` | 414 | `tests/test_nats_bus.py` |
| `backend/api/routes/compliance_reports.py` | 409 | `tests/test_compliance_reports.py` |
| `backend/api/routes/meta_learning.py` | 400 | `tests/test_meta_learning.py` |

## High Priority (200–399 lines)

| File | Lines | Suggested Test File |
|---|---|---|
| `backend/database/repositories/approval_repository.py` | 391 | `tests/test_approval_repository.py` |
| `backend/meta_learning/performance_tracker.py` | 381 | `tests/test_performance_tracker.py` |
| `backend/integrations/observability/prometheus_metrics.py` | 375 | `tests/test_prometheus_metrics.py` |
| `backend/agents/workflows/reasoning_graph.py` | 366 | `tests/test_reasoning_graph.py` |
| `backend/agents/compliance/rate_limiter.py` | 364 | `tests/test_rate_limiter.py` |
| `backend/core/vault/vault_service.py` | 347 | `tests/test_vault_service.py` |
| `backend/api/routes/campaigns.py` | 337 | `tests/test_campaigns.py` |
| `backend/api/routes/performance.py` | 333 | `tests/test_performance.py` |
| `backend/core/logging_config.py` | 332 | `tests/test_logging_config.py` |
| `backend/agents/factory/agent_factory.py` | 326 | `tests/test_agent_factory.py` |
| `backend/database/repositories/policy_repository.py` | 325 | `tests/test_policy_repository.py` |
| `backend/integrations/mcp/tool_bridge.py` | 320 | `tests/test_tool_bridge.py` |
| `backend/orchestration/lead_generation_workflow.py` | 312 | `tests/test_lead_generation_workflow.py` |
| `backend/integrations/tools/browser_tool.py` | 309 | `tests/test_browser_tool.py` |
| `backend/integrations/tools/reddit_tool.py` | 308 | `tests/test_reddit_tool.py` |
| `backend/agents/base/base_agent_v3.py` | 301 | `tests/test_base_agent_v3.py` |
| `backend/agents/compliance/approval.py` | 301 | `tests/test_approval.py` |
| `backend/integrations/tools/twitter_tool.py` | 285 | `tests/test_twitter_tool.py` |
| `backend/middleware/governance_rate_limit.py` | 284 | `tests/test_governance_rate_limit.py` |
| `backend/api/routes/approval.py` | 279 | `tests/test_approval.py` |
| `backend/database/optimization.py` | 278 | `tests/test_optimization.py` |
| `backend/integrations/llm/llm_service.py` | 269 | `tests/test_llm_service.py` |
| `backend/integrations/mcp/server_registry.py` | 260 | `tests/test_server_registry.py` |
| `backend/integrations/observability/telemetry.py` | 257 | `tests/test_telemetry.py` |
| `backend/api/routes/vault.py` | 254 | `tests/test_vault.py` |
| `backend/database/repositories/base.py` | 247 | `tests/test_base.py` |
| `backend/api/routes/tenants.py` | 245 | `tests/test_tenants.py` |
| `backend/agents/compliance/engine.py` | 233 | `tests/test_engine.py` |
| `backend/middleware/auth/governance_auth.py` | 225 | `tests/test_governance_auth.py` |
| `backend/integrations/llm/llm_factory.py` | 224 | `tests/test_llm_factory.py` |
| `backend/agents/implementations/commander_agent_v3.py` | 221 | `tests/test_commander_agent_v3.py` |
| `backend/security/sanitisation.py` | 219 | `tests/test_sanitisation.py` |
| `backend/agents/implementations/commander_agent_v3_updated.py` | 208 | `tests/test_commander_agent_v3_updated.py` |
| `backend/database/repositories/lineage_repository.py` | 206 | `tests/test_lineage_repository.py` |

## Medium Priority (50–199 lines)

| File | Lines | Suggested Test File |
|---|---|---|
| `backend/core/cqrs/setup.py` | 194 | `tests/test_setup.py` |
| `backend/agents/compliance/registry.py` | 178 | `tests/test_registry.py` |
| `backend/middleware/auth/auth_middleware.py` | 178 | `tests/test_auth_middleware.py` |
| `backend/middleware/rate_limit.py` | 176 | `tests/test_rate_limit.py` |
| `backend/agents/implementations/compliance_wrapper.py` | 175 | `tests/test_compliance_wrapper.py` |
| `backend/core/event_sourcing/event_store.py` | 166 | `tests/test_event_store.py` |
| `backend/database/session.py` | 156 | `tests/test_session.py` |
| `backend/api/middleware/logging_middleware.py` | 154 | `tests/test_logging_middleware.py` |
| `backend/integrations/mcp/setup.py` | 144 | `tests/test_setup.py` |
| `backend/agents/governance/pride_kernel.py` | 132 | `tests/test_pride_kernel.py` |
| `backend/agents/compliance/models.py` | 126 | `tests/test_models.py` |
| `backend/config/settings.py` | 119 | `tests/test_settings.py` |
| `backend/middleware/security_headers.py` | 119 | `tests/test_security_headers.py` |
| `backend/api/routes/economy.py` | 111 | `tests/test_economy.py` |
| `backend/integrations/llm/llm_metrics_wrapper.py` | 104 | `tests/test_llm_metrics_wrapper.py` |
| `backend/security/secrets_validator.py` | 103 | `tests/test_secrets_validator.py` |
| `backend/models/domain/user.py` | 87 | `tests/test_user.py` |
| `backend/version.py` | 73 | `tests/test_version.py` |
| `backend/models/domain/mission.py` | 65 | `tests/test_mission.py` |
| `backend/integrations/mcp/tool_server.py` | 54 | `tests/test_tool_server.py` |
| `backend/models/domain/agent.py` | 51 | `tests/test_agent.py` |

## Low Priority (< 50 lines)

| File | Lines | Suggested Test File |
|---|---|---|
| `backend/database/init_db.py` | 33 | `tests/test_init_db.py` |
| `backend/api/routes/metrics.py` | 19 | `tests/test_metrics.py` |
| `backend/database/base.py` | 10 | `tests/test_base.py` |

## Recommended Test Writing Order

The following is the prioritized order for adding test coverage, starting with the largest and most architecturally critical files.

1. `backend/core/saga/saga_orchestrator.py` (1627 lines)
2. `backend/core/cqrs/cqrs_impl.py` (916 lines)
3. `backend/api/routes/agents.py` (907 lines)
4. `backend/api/routes/missions.py` (820 lines)
5. `backend/agents/compliance/rules.py` (756 lines)
6. `backend/orchestration/mission_executor.py` (741 lines)
7. `backend/orchestration/workforce_coordinator.py` (707 lines)
8. `backend/orchestration/revenue_agent.py` (696 lines)
9. `backend/agents/integration/nats_governance.py` (687 lines)
10. `backend/api/routes/tags.py` (644 lines)
11. `backend/api/routes/revenue.py` (642 lines)
12. `backend/api/routes/risk.py` (632 lines)
13. `backend/core/scheduler/scheduler_service.py` (612 lines)
14. `backend/core/event_sourcing/event_store_impl.py` (604 lines)
15. `backend/main.py` (596 lines)
16. `backend/database/models.py` (567 lines)
17. `backend/api/routes/policies.py` (550 lines)
18. `backend/integrations/mcp/mcp_client.py` (546 lines)
19. `backend/database/governance_models.py` (545 lines)
20. `backend/economy/resource_marketplace.py` (545 lines)
