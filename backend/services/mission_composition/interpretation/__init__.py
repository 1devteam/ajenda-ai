"""Mission-language interpretation boundary.

The local model produces an untrusted, grounded language interpretation. All
ability selection, policy, permission, compile, and runtime authority remains
outside this package.
"""

from backend.services.mission_composition.interpretation.interpreter import (
    LlmMissionInterpreter,
    MissionInterpreter,
    MissionInterpreterOutputError,
    build_mission_interpreter,
)

__all__ = [
    "LlmMissionInterpreter",
    "MissionInterpreter",
    "MissionInterpreterOutputError",
    "build_mission_interpreter",
]
