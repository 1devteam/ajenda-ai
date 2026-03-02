"""
Citadel Governance Module
==========================
Provides the immutable Pride Protocol governance layer for all agents
operating inside the Citadel platform.

Public API:
    - assemble_prompt: Prepend the Pride preamble to any agent system prompt
    - is_pride_compliant: Verify a prompt contains the governance block
    - get_preamble_version: Get the current preamble version string
    - PRIDE_PREAMBLE: The raw preamble constant (read-only reference)
    - PRIDE_PROTOCOL_VERSION: Current protocol version string
"""

from backend.agents.governance.pride_kernel import (
    PRIDE_PREAMBLE,
    PRIDE_PROTOCOL_VERSION,
    assemble_prompt,
    get_preamble_version,
    is_pride_compliant,
)

__all__ = [
    "PRIDE_PREAMBLE",
    "PRIDE_PROTOCOL_VERSION",
    "assemble_prompt",
    "get_preamble_version",
    "is_pride_compliant",
]
