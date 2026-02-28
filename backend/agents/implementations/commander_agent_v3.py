"""
Commander Agent v3.0
Enhanced with event sourcing, observability, and async messaging.
"""

from typing import Dict, Any
import asyncio

from backend.agents.base.base_agent import BaseAgent
from backend.core.event_sourcing.event_store import EventSourcedAggregate
from backend.core.event_bus.nats_bus import event_bus, Subjects
from backend.integrations.observability.telemetry import traced
from backend.integrations.observability.langfuse_integration import trace_llm


class CommanderAggregate(EventSourcedAggregate):
    """
    Event-sourced aggregate for Commander agent state.
    """

    def __init__(self, aggregate_id: str):
        super().__init__(aggregate_id)

        # State
        self.emotion = "neutral"
        self.intensity = 0.0
        self.risk_score = 0.0
        self.reflex_patterns = {}
        self.decision_count = 0

    def apply_CommanderCreated(self, data: Dict[str, Any]):
        """Apply CommanderCreated event."""
        self.reflex_patterns = data.get("reflex_patterns", {})

    def apply_DecisionMade(self, data: Dict[str, Any]):
        """Apply DecisionMade event."""
        self.emotion = data["emotion"]
        self.intensity = data["intensity"]
        self.risk_score = data["risk_score"]
        self.decision_count += 1

    def apply_ReflexApplied(self, data: Dict[str, Any]):
        """Apply ReflexApplied event."""
        self.emotion = data["final_emotion"]


class CommanderAgentV3(BaseAgent):
    """
    Commander agent with emotional intelligence and event sourcing.

    Enhancements in v3:
    - Event-sourced state management
    - Async NATS messaging
    - OpenTelemetry tracing
    - Langfuse LLM observability
    """

    EMOTION_WEIGHTS = {
        "joy": 2,
        "resolve": 1,
        "curiosity": 3,
        "neutral": 1,
        "sadness": 8,
        "anger": 9,
        "fear": 7,
        "duty": 4,
        "grief": 9,
    }

    def __init__(
        self,
        agent_id: str,
        agent_name: str,
        tenant_id: str,
        mission_payload: Dict[str, Any],
        configuration: Dict[str, Any] = None,
    ):
        super().__init__(
            agent_id, agent_name, tenant_id, mission_payload, configuration
        )

        # Event-sourced aggregate
        self.aggregate = CommanderAggregate(agent_id)

        # Load reflex patterns
        self.reflex_patterns = self.get_config("reflex_patterns", {})

        # Record creation event
        self.aggregate.record_event(
            "CommanderCreated",
            {
                "agent_id": agent_id,
                "agent_name": agent_name,
                "tenant_id": tenant_id,
                "reflex_patterns": self.reflex_patterns,
            },
        )

    def validate_mission(self) -> bool:
        """Validate mission payload."""
        required_fields = ["signal", "emotion", "intensity"]

        for field in required_fields:
            if field not in self.mission_payload:
                self.log_error(f"Missing required field: {field}")
                return False

        emotion = self.mission_payload.get("emotion")
        if emotion not in self.EMOTION_WEIGHTS:
            self.log_warning(f"Unknown emotion: {emotion}, using default weight")

        return True

    @traced("commander.execute_mission")
    @trace_llm("commander_decision")
    def execute_mission(self) -> Dict[str, Any]:
        """
        Execute the commander's decision-making process.

        Returns:
            Decision results with event-sourced state
        """
        signal = self.mission_payload["signal"]
        emotion = self.mission_payload["emotion"]
        intensity = self.mission_payload["intensity"]

        self.log_info(
            f"Evaluating signal '{signal}' with emotion '{emotion}' at intensity {intensity}"
        )

        # Apply reflex substitution
        reflex_result = self._apply_reflex(signal, emotion)
        final_emotion = reflex_result["final_emotion"]

        # Record reflex event if changed
        if final_emotion != emotion:
            self.aggregate.record_event(
                "ReflexApplied",
                {
                    "original_emotion": emotion,
                    "final_emotion": final_emotion,
                    "signal": signal,
                    "rationale": reflex_result.get("rationale"),
                },
            )

        # Calculate risk score
        risk_score = self._calculate_risk(final_emotion, intensity)

        # Determine pulse
        pulse = "EXECUTED" if risk_score < 7 else "BLOCKED"

        # Record decision event
        self.aggregate.record_event(
            "DecisionMade",
            {
                "signal": signal,
                "emotion": final_emotion,
                "intensity": intensity,
                "risk_score": risk_score,
                "pulse": pulse,
            },
        )

        result = {
            "signal": signal,
            "original_emotion": emotion,
            "final_emotion": final_emotion,
            "intensity": intensity,
            "risk_score": risk_score,
            "pulse": pulse,
            "reflex_status": reflex_result["status"],
            "rationale": reflex_result.get("rationale"),
            "decision_count": self.aggregate.decision_count,
            "aggregate_version": self.aggregate.version,
        }

        self.log_info(f"Decision: {pulse} (risk score: {risk_score})")

        # Publish decision event to NATS
        asyncio.create_task(self._publish_decision(result))

        return result

    def _apply_reflex(self, signal: str, emotion: str) -> Dict[str, Any]:
        """Apply reflex substitution based on learned patterns."""
        if signal in self.reflex_patterns:
            pattern = self.reflex_patterns[signal]

            if emotion == pattern.get("substitute_from"):
                return {
                    "final_emotion": pattern.get("substitute_to"),
                    "status": "RECOMMENDED",
                    "rationale": pattern.get("rationale"),
                }

        return {"final_emotion": emotion, "status": "UNCHANGED"}

    def _calculate_risk(self, emotion: str, intensity: float) -> float:
        """Calculate risk score based on emotion and intensity."""
        base_weight = self.EMOTION_WEIGHTS.get(emotion, 5)
        risk_score = min(10, base_weight + (intensity * 0.5))

        return round(risk_score, 2)

    async def _publish_decision(self, decision: Dict[str, Any]):
        """Publish decision to NATS event bus."""
        try:
            subject = Subjects.format(Subjects.AGENT_RESPONSE, agent_id=self.agent_id)

            await event_bus.publish(
                subject=subject,
                data={
                    "agent_id": self.agent_id,
                    "agent_type": "commander",
                    "decision": decision,
                },
            )

            self.log_info(f"Published decision to {subject}")

        except Exception as e:
            self.log_error(f"Failed to publish decision: {e}")
