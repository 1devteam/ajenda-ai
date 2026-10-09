"""Stable contracts shared by mission-composition service phases."""

from __future__ import annotations


class MissionCompositionError(ValueError):
    def __init__(self, *, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


COMPILER_NAME = "ajenda-mission-compiler"
COMPILER_VERSION = "1.0.0"
