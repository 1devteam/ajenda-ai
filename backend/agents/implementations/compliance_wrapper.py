"""
Compliance wrapper for specialized agents.

This module provides a mixin that adds compliance checking to tool execution
for agents that don't inherit from BaseAgentV3.

Built with Pride for Obex Blackvault
"""

from typing import Dict, Any, Optional
import logging

from backend.agents.compliance import ComplianceEngine

logger = logging.getLogger(__name__)


class ComplianceAwareMixin:
    """
    Mixin that adds compliance checking to specialized agents.

    Usage:
        class MyAgent(ComplianceAwareMixin):
            def __init__(self, ...):
                self.agent_id = agent_id
                self.agent_type = "my_type"
                self.tenant_id = tenant_id
                self._init_compliance()  # Initialize compliance

            async def execute_task(self):
                # Use compliance-checked tool execution
                result = await self._execute_tool_with_compliance(
                    "web_search",
                    self.web_search,
                    {"query": "test"}
                )

    Requirements:
        - Agent must have: agent_id, agent_type, tenant_id attributes
        - Tools must have: execute(**params) async method
    """

    def _init_compliance(self):
        """
        Initialize compliance engine.

        Call this in your agent's __init__ after setting:
        - self.agent_id
        - self.agent_type
        - self.tenant_id
        """
        if not hasattr(self, "agent_id"):
            raise AttributeError(
                "Agent must have 'agent_id' attribute before initializing compliance"
            )
        if not hasattr(self, "agent_type"):
            raise AttributeError(
                "Agent must have 'agent_type' attribute before initializing compliance"
            )
        if not hasattr(self, "tenant_id"):
            raise AttributeError(
                "Agent must have 'tenant_id' attribute before initializing compliance"
            )

        self.compliance_engine = ComplianceEngine()
        logger.info(
            f"Compliance engine initialized for {self.agent_type} agent {self.agent_id}"
        )

    def _build_compliance_context(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        mission_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build compliance context for tool execution.

        Args:
            tool_name: Name of the tool being executed
            parameters: Tool parameters
            mission_payload: Optional mission/task context

        Returns:
            Context dictionary for compliance evaluation
        """
        context = {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "tenant_id": self.tenant_id,
            "tool_name": tool_name,
            "parameters": parameters,
        }

        if mission_payload:
            context["mission_payload"] = mission_payload

        return context

    async def _execute_tool_with_compliance(
        self,
        tool_name: str,
        tool_instance: Any,
        parameters: Dict[str, Any],
        mission_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute tool with compliance checking.

        This method wraps tool execution with compliance checks,
        ensuring all tool usage is authorized and auditable.

        Args:
            tool_name: Name of the tool
            tool_instance: Tool instance to execute
            parameters: Tool parameters
            mission_payload: Optional mission/task context for justification

        Returns:
            Tool result with compliance traces

        Example:
            result = await self._execute_tool_with_compliance(
                tool_name="web_search",
                tool_instance=self.web_search,
                parameters={"query": "test", "max_results": 10},
                mission_payload={"task": "research AI trends"}
            )

            if not result.get("success"):
                print(f"Blocked: {result.get('error')}")
                print(f"Reason: {result.get('compliance_evaluation')}")
        """
        # Build compliance context
        context = self._build_compliance_context(tool_name, parameters, mission_payload)

        # Evaluate compliance
        evaluation = self.compliance_engine.evaluate(tool_name, context)

        # Block if not allowed
        if not evaluation.allowed:
            logger.warning(
                f"Tool execution blocked by compliance: {tool_name} "
                f"for {self.agent_type} agent {self.agent_id}. "
                f"Reason: {evaluation.reason}"
            )
            return {
                "success": False,
                "error": f"Compliance denied: {evaluation.reason}",
                "compliance_evaluation": evaluation.to_dict(),
                "blocked_by": evaluation.blocked_by,
            }

        # Execute tool
        try:
            logger.debug(
                f"Executing tool {tool_name} for {self.agent_type} agent {self.agent_id} "
                f"(passed {len(evaluation.passed_rules)} compliance rules)"
            )

            result = await tool_instance.execute(**parameters)

            # Add compliance traces to result
            if isinstance(result, dict):
                result["compliance_evaluation"] = evaluation.to_dict()
                result["compliance_passed"] = True

            return result

        except Exception as e:
            logger.error(f"Tool execution failed: {tool_name} - {e}")
            return {
                "success": False,
                "error": str(e),
                "compliance_evaluation": evaluation.to_dict(),
                "compliance_passed": True,  # Compliance passed, but execution failed
            }
