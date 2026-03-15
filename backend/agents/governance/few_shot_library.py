"""
Few-Shot Reference Library
===========================
Provides a scalable library of positive and negative examples for agent
scenarios. These examples are injected into agent prompts at assembly time
to give the model concrete demonstrations of correct and incorrect behaviour.

This is the practical, scenario-specific extension of the Pride Protocol:
the preamble defines the principles, the examples demonstrate them in action.

Design decisions:
  - Examples are stored in a static JSON file (few_shot_library.json).
    They are engineering assets, not runtime data, so a database table
    would be over-engineering. Adding new examples requires no code changes.
  - The library is loaded once and cached in memory as a module-level
    singleton. There is no I/O overhead after the first call.
  - Retrieval always returns a balanced set: at least one positive and one
    negative example per scenario, up to the requested count.
  - The formatted output is pure markdown, compatible with all LLM providers.

Author: Dev Team Lead
Built with Pride for Obex Blackvault
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Path to the JSON library file — co-located with the governance module
_LIBRARY_PATH = Path(__file__).parent / "few_shot_library.json"


# ============================================================================
# Data Model
# ============================================================================


@dataclass(frozen=True)
class FewShotExample:
    """
    A single few-shot reference example.

    Attributes:
        scenario:    The scenario this example applies to (e.g. "lead_qualification").
        type:        "positive" for a good example, "negative" for a bad one.
        input:       A representative input for the scenario.
        output:      The corresponding output (good or bad).
        explanation: Why this is a good or bad example, tied to Pride Protocol.
        tags:        Optional tags for fine-grained filtering.
    """

    scenario: str
    type: str  # "positive" | "negative"
    input: str
    output: str
    explanation: str
    tags: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.type not in ("positive", "negative"):
            raise ValueError(
                f"FewShotExample.type must be 'positive' or 'negative', got: {self.type!r}"
            )
        if not self.scenario.strip():
            raise ValueError("FewShotExample.scenario must not be empty.")
        if not self.input.strip():
            raise ValueError("FewShotExample.input must not be empty.")
        if not self.output.strip():
            raise ValueError("FewShotExample.output must not be empty.")
        if not self.explanation.strip():
            raise ValueError("FewShotExample.explanation must not be empty.")


# ============================================================================
# Library
# ============================================================================


class FewShotLibrary:
    """
    In-memory library of few-shot reference examples.

    Loaded once from few_shot_library.json and cached for the lifetime of
    the process. Thread-safe for reads (no mutation after load).

    Usage:
        library = FewShotLibrary.get_instance()
        examples = library.get_examples("lead_qualification", count=2)
        block = library.format_examples_block("lead_qualification")
    """

    _instance: Optional["FewShotLibrary"] = None
    _examples: List[FewShotExample]
    _index: Dict[str, List[FewShotExample]]  # scenario -> examples

    def __init__(self, library_path: Path = _LIBRARY_PATH) -> None:
        """
        Load and index the example library from a JSON file.

        Args:
            library_path: Path to the JSON file. Defaults to the co-located
                          few_shot_library.json in the governance directory.

        Raises:
            FileNotFoundError: If the library file does not exist.
            ValueError: If any example fails schema validation.
        """
        if not library_path.exists():
            raise FileNotFoundError(
                f"Few-shot library not found at: {library_path}\n"
                "Create backend/agents/governance/few_shot_library.json "
                "to enable few-shot injection."
            )

        raw = json.loads(library_path.read_text(encoding="utf-8"))
        self._examples = []
        self._index = {}

        for i, item in enumerate(raw):
            try:
                example = FewShotExample(
                    scenario=item["scenario"],
                    type=item["type"],
                    input=item["input"],
                    output=item["output"],
                    explanation=item["explanation"],
                    tags=item.get("tags", []),
                )
                self._examples.append(example)
                self._index.setdefault(example.scenario, []).append(example)
            except (KeyError, ValueError) as exc:
                raise ValueError(f"Invalid few-shot example at index {i}: {exc}") from exc

        logger.info(
            "FewShotLibrary loaded: %d examples across %d scenarios",
            len(self._examples),
            len(self._index),
        )

    @classmethod
    def get_instance(cls, library_path: Path = _LIBRARY_PATH) -> "FewShotLibrary":
        """
        Return the module-level singleton, loading it on first call.

        Args:
            library_path: Override the default path (useful in tests).

        Returns:
            The shared FewShotLibrary instance.
        """
        if cls._instance is None:
            cls._instance = cls(library_path=library_path)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """
        Clear the singleton. Used in tests to reload the library with a
        different file path without cross-test contamination.
        """
        cls._instance = None

    # -----------------------------------------------------------------------
    # Retrieval
    # -----------------------------------------------------------------------

    def list_scenarios(self) -> List[str]:
        """Return all scenario names that have at least one example."""
        return sorted(self._index.keys())

    def get_examples(
        self,
        scenario: str,
        count: int = 2,
        tags: Optional[List[str]] = None,
    ) -> List[FewShotExample]:
        """
        Retrieve a balanced set of examples for a scenario.

        Always returns at least one positive and one negative example when
        both are available. If count > 2, additional examples are added
        alternating positive/negative until count is reached.

        Args:
            scenario: The scenario name to retrieve examples for.
            count:    Maximum number of examples to return (minimum 1).
            tags:     Optional list of tags to filter by. An example must
                      have ALL specified tags to be included.

        Returns:
            A list of FewShotExample objects, positive examples first.
            Returns an empty list if the scenario has no examples.
        """
        if count < 1:
            raise ValueError(f"count must be >= 1, got {count}")

        candidates = self._index.get(scenario, [])

        if tags:
            tag_set = set(tags)
            candidates = [e for e in candidates if tag_set.issubset(set(e.tags))]

        if not candidates:
            return []

        positives = [e for e in candidates if e.type == "positive"]
        negatives = [e for e in candidates if e.type == "negative"]

        result: List[FewShotExample] = []
        pos_iter = iter(positives)
        neg_iter = iter(negatives)

        # Always lead with a positive example
        for source in (pos_iter, neg_iter, pos_iter, neg_iter, pos_iter, neg_iter):
            if len(result) >= count:
                break
            try:
                result.append(next(source))
            except StopIteration:
                continue

        return result[:count]

    # -----------------------------------------------------------------------
    # Formatting
    # -----------------------------------------------------------------------

    def format_examples_block(
        self,
        scenario: str,
        count: int = 2,
        tags: Optional[List[str]] = None,
    ) -> str:
        """
        Format the examples for a scenario into a markdown block suitable
        for injection into an LLM system prompt.

        Args:
            scenario: The scenario name.
            count:    Maximum number of examples to include.
            tags:     Optional tag filter.

        Returns:
            A formatted markdown string, or an empty string if no examples
            exist for the scenario.
        """
        examples = self.get_examples(scenario, count=count, tags=tags)
        if not examples:
            return ""

        lines = [
            "---",
            f"## Reference Examples: {scenario.replace('_', ' ').title()}",
            "",
            "Study these examples carefully. They demonstrate the difference between",
            "proper and improper actions for this specific task.",
            "",
        ]

        for i, example in enumerate(examples, 1):
            if example.type == "positive":
                header = "### ✅ PROPER ACTION — Example"
            else:
                header = "### ❌ IMPROPER ACTION — Example"

            if len(examples) > 1:
                header = f"{header} {i}"

            lines.append(header)
            lines.append("")
            lines.append("**INPUT**:")
            lines.append("```")
            lines.append(example.input.strip())
            lines.append("```")
            lines.append("")
            lines.append("**OUTPUT**:")
            lines.append("```")
            lines.append(example.output.strip())
            lines.append("```")
            lines.append("")
            lines.append(f"**WHY**: {example.explanation.strip()}")
            lines.append("")

        lines.append("---")
        lines.append("")
        return "\n".join(lines)
