"""
Commander Agent v3 - Enhanced with Multi-Model Support
"""

from typing import Dict, Any
from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.base.base_agent_v3 import BaseAgentV3


class CommanderAgentV3(BaseAgentV3):
    """
    Commander Agent: Decision-making with emotional intelligence.

    Features:
    - Multi-model LLM support with easy switching
    - Emotional state tracking
    - Risk assessment
    - Reflex substitution learning
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Emotional state
        self.emotional_state = {"mood": "neutral", "intensity": 5, "drift": 0.0}

        # Risk assessment
        self.risk_threshold = self.configuration.get("risk_threshold", 0.7)

    async def validate(self):
        """Validate mission parameters"""
        required_fields = ["command", "message"]
        for field in required_fields:
            if field not in self.mission_payload:
                raise ValueError(f"Missing required field: {field}")

    async def initialize(self):
        """Initialize Commander resources"""
        # Load reflex patterns if configured
        self.reflex_patterns = self.configuration.get("reflex_patterns", {})

        # Initialize emotional state from payload if provided
        if "emotion" in self.mission_payload:
            self.emotional_state["mood"] = self.mission_payload["emotion"]
        if "intensity" in self.mission_payload:
            self.emotional_state["intensity"] = self.mission_payload["intensity"]

    async def run(self) -> Dict[str, Any]:
        """Execute Commander logic with LLM"""
        command = self.mission_payload["command"]
        message = self.mission_payload["message"]

        if command == "evaluate":
            return await self._evaluate_signal(message)
        elif command == "decide":
            return await self._make_decision(message)
        elif command == "reflect":
            return await self._reflect_on_action(message)
        else:
            raise ValueError(f"Unknown command: {command}")

    async def _evaluate_signal(self, signal: str) -> Dict[str, Any]:
        """Evaluate a signal with emotional context"""

        # Build prompt with emotional context
        system_prompt = f"""You are the Commander agent in a multi-agent system.
Your current emotional state: {self.emotional_state['mood']} (intensity: {self.emotional_state['intensity']}/10)  # noqa: E501

Evaluate the following signal and provide:
1. Risk score (0.0 to 1.0)
2. Recommended action
3. Reasoning

Consider your emotional state in your evaluation."""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Signal: {signal}"),
        ]

        # Use the LLM (automatically selected based on configuration)
        response = await self.llm.ainvoke(messages)

        # Parse response
        risk_score = self._extract_risk_score(response.content)

        return {
            "signal": signal,
            "risk_score": risk_score,
            "emotional_state": self.emotional_state,
            "response": response.content,
            "model_used": f"{self._get_llm_config()[0]}/{self._get_llm_config()[1]}",
        }

    async def _make_decision(self, context: str) -> Dict[str, Any]:
        """Make a decision based on context"""

        system_prompt = f"""You are the Commander agent making a critical decision.
Emotional state: {self.emotional_state['mood']} (intensity: {self.emotional_state['intensity']}/10)
Risk threshold: {self.risk_threshold}

Analyze the context and make a decision. Provide:
1. Your decision (approve/reject/defer)
2. Confidence level (0.0 to 1.0)
3. Reasoning"""

        messages = [SystemMessage(content=system_prompt), HumanMessage(content=context)]

        response = await self.llm.ainvoke(messages)

        return {
            "decision": self._extract_decision(response.content),
            "confidence": self._extract_confidence(response.content),
            "reasoning": response.content,
            "model_used": f"{self._get_llm_config()[0]}/{self._get_llm_config()[1]}",
        }

    async def _reflect_on_action(self, action: str) -> Dict[str, Any]:
        """Reflect on a completed action"""

        system_prompt = """You are the Commander agent reflecting on a completed action.
Analyze what happened and extract lessons learned."""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Action: {action}"),
        ]

        response = await self.llm.ainvoke(messages)

        return {
            "reflection": response.content,
            "model_used": f"{self._get_llm_config()[0]}/{self._get_llm_config()[1]}",
        }

    def _extract_risk_score(self, content: str) -> float:
        """Extract risk score from LLM response"""
        # Simple extraction - in production, use structured output
        import re

        match = re.search(r"risk.*?(\d+\.?\d*)", content.lower())
        if match:
            score = float(match.group(1))
            return min(max(score, 0.0), 1.0)
        return 0.5  # Default

    def _extract_confidence(self, content: str) -> float:
        """
        Extract confidence level (0.0–1.0) from LLM response text.

        Looks for patterns like:
          - "confidence: 0.9"
          - "confidence level: 90%"
          - "I am 85% confident"
          - "confidence of 0.75"

        Falls back to 0.7 if no match is found.

        Args:
            content: Raw LLM response text.

        Returns:
            Float in [0.0, 1.0].
        """
        import re

        # Pattern 1: decimal confidence (e.g. "confidence: 0.85" or "confidence of 0.9")
        decimal_match = re.search(r"confidence[^\d]{0,20}(\d+\.\d+)", content.lower())
        if decimal_match:
            score = float(decimal_match.group(1))
            return min(max(score, 0.0), 1.0)

        # Pattern 2: percentage confidence (e.g. "85% confident" or "confidence: 90%")
        percent_match = re.search(r"(\d{1,3})\s*%\s*confiden", content.lower()) or re.search(
            r"confiden[a-z\s]{0,20}(\d{1,3})\s*%", content.lower()
        )
        if percent_match:
            score = float(percent_match.group(1)) / 100.0
            return min(max(score, 0.0), 1.0)

        # Pattern 3: standalone decimal in [0,1] near "confidence" keyword
        near_match = re.search(r"confiden[a-z\s]{0,30}(0\.\d+|1\.0)", content.lower())
        if near_match:
            score = float(near_match.group(1))
            return min(max(score, 0.0), 1.0)

        return 0.7  # Conservative default when confidence is not stated

    def _extract_decision(self, content: str) -> str:
        """Extract decision from LLM response"""
        content_lower = content.lower()
        if "approve" in content_lower:
            return "approve"
        elif "reject" in content_lower:
            return "reject"
        else:
            return "defer"
