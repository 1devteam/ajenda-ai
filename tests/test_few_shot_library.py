"""
Tests for the Few-Shot Reference Library System
================================================
Covers:
  - FewShotExample data model validation
  - FewShotLibrary loading, indexing, and retrieval
  - Balanced positive/negative example retrieval
  - Tag-based filtering
  - Markdown block formatting
  - assemble_prompt integration (with and without scenario)
  - Graceful degradation when library file is missing
  - Singleton pattern and reset behaviour

Author: Dev Team Lead
Built with Pride for Obex Blackvault
"""

import json
from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_EXAMPLE = {
    "scenario": "lead_qualification",
    "type": "positive",
    "input": "Company: Acme Corp\nIndustry: retail",
    "output": '{"qualification_score": 0.8}',
    "explanation": "This is a proper action because all fields are present.",
    "tags": ["json_format"],
}

NEGATIVE_EXAMPLE = {
    "scenario": "lead_qualification",
    "type": "negative",
    "input": "Company: Bad Corp\nIndustry: retail",
    "output": '{"qualification_score": 0.5}',
    "explanation": "This is an improper action because the score is a default.",
    "tags": ["json_format"],
}

SECOND_SCENARIO_EXAMPLE = {
    "scenario": "proposal_writing",
    "type": "positive",
    "input": "Target: Acme Corp",
    "output": '{"title": "Great Proposal"}',
    "explanation": "This is a proper action because it is specific.",
    "tags": ["revenue_pipeline"],
}


def _write_library(tmp_path: Path, examples: List[dict]) -> Path:
    """Write a temporary library JSON file and return its path."""
    lib_path = tmp_path / "few_shot_library.json"
    lib_path.write_text(json.dumps(examples), encoding="utf-8")
    return lib_path


# ---------------------------------------------------------------------------
# FewShotExample Tests
# ---------------------------------------------------------------------------


class TestFewShotExample:
    """Tests for the FewShotExample dataclass validation."""

    def test_valid_positive_example(self):
        from backend.agents.governance.few_shot_library import FewShotExample

        ex = FewShotExample(**{k: v for k, v in VALID_EXAMPLE.items() if k != "tags"})
        assert ex.scenario == "lead_qualification"
        assert ex.type == "positive"
        assert ex.tags == []

    def test_valid_negative_example(self):
        from backend.agents.governance.few_shot_library import FewShotExample

        ex = FewShotExample(**{k: v for k, v in NEGATIVE_EXAMPLE.items()})
        assert ex.type == "negative"

    def test_invalid_type_raises(self):
        from backend.agents.governance.few_shot_library import FewShotExample

        with pytest.raises(ValueError, match="positive.*negative"):
            FewShotExample(
                scenario="test",
                type="maybe",
                input="x",
                output="y",
                explanation="z",
            )

    def test_empty_scenario_raises(self):
        from backend.agents.governance.few_shot_library import FewShotExample

        with pytest.raises(ValueError, match="scenario"):
            FewShotExample(
                scenario="   ",
                type="positive",
                input="x",
                output="y",
                explanation="z",
            )

    def test_empty_input_raises(self):
        from backend.agents.governance.few_shot_library import FewShotExample

        with pytest.raises(ValueError, match="input"):
            FewShotExample(
                scenario="test",
                type="positive",
                input="",
                output="y",
                explanation="z",
            )

    def test_empty_output_raises(self):
        from backend.agents.governance.few_shot_library import FewShotExample

        with pytest.raises(ValueError, match="output"):
            FewShotExample(
                scenario="test",
                type="positive",
                input="x",
                output="",
                explanation="z",
            )

    def test_empty_explanation_raises(self):
        from backend.agents.governance.few_shot_library import FewShotExample

        with pytest.raises(ValueError, match="explanation"):
            FewShotExample(
                scenario="test",
                type="positive",
                input="x",
                output="y",
                explanation="",
            )

    def test_tags_default_to_empty_list(self):
        from backend.agents.governance.few_shot_library import FewShotExample

        ex = FewShotExample(
            scenario="test",
            type="positive",
            input="x",
            output="y",
            explanation="z",
        )
        assert ex.tags == []

    def test_example_is_immutable(self):
        """FewShotExample is frozen — mutation must raise AttributeError."""
        from backend.agents.governance.few_shot_library import FewShotExample

        ex = FewShotExample(
            scenario="test",
            type="positive",
            input="x",
            output="y",
            explanation="z",
        )
        with pytest.raises(AttributeError):
            ex.scenario = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# FewShotLibrary Loading Tests
# ---------------------------------------------------------------------------


class TestFewShotLibraryLoading:
    """Tests for library loading and indexing."""

    def setup_method(self):
        from backend.agents.governance.few_shot_library import FewShotLibrary

        FewShotLibrary.reset_instance()

    def test_loads_valid_library(self, tmp_path):
        from backend.agents.governance.few_shot_library import FewShotLibrary

        lib_path = _write_library(tmp_path, [VALID_EXAMPLE, NEGATIVE_EXAMPLE])
        lib = FewShotLibrary(library_path=lib_path)
        assert len(lib._examples) == 2

    def test_raises_on_missing_file(self, tmp_path):
        from backend.agents.governance.few_shot_library import FewShotLibrary

        with pytest.raises(FileNotFoundError):
            FewShotLibrary(library_path=tmp_path / "nonexistent.json")

    def test_raises_on_invalid_example_type(self, tmp_path):
        from backend.agents.governance.few_shot_library import FewShotLibrary

        bad = {**VALID_EXAMPLE, "type": "unknown"}
        lib_path = _write_library(tmp_path, [bad])
        with pytest.raises(ValueError, match="Invalid few-shot example at index 0"):
            FewShotLibrary(library_path=lib_path)

    def test_raises_on_missing_required_field(self, tmp_path):
        from backend.agents.governance.few_shot_library import FewShotLibrary

        bad = {k: v for k, v in VALID_EXAMPLE.items() if k != "explanation"}
        lib_path = _write_library(tmp_path, [bad])
        with pytest.raises(ValueError, match="Invalid few-shot example at index 0"):
            FewShotLibrary(library_path=lib_path)

    def test_list_scenarios(self, tmp_path):
        from backend.agents.governance.few_shot_library import FewShotLibrary

        lib_path = _write_library(
            tmp_path, [VALID_EXAMPLE, NEGATIVE_EXAMPLE, SECOND_SCENARIO_EXAMPLE]
        )
        lib = FewShotLibrary(library_path=lib_path)
        scenarios = lib.list_scenarios()
        assert "lead_qualification" in scenarios
        assert "proposal_writing" in scenarios
        assert scenarios == sorted(scenarios)  # Must be sorted

    def test_singleton_pattern(self, tmp_path):
        from backend.agents.governance.few_shot_library import FewShotLibrary

        lib_path = _write_library(tmp_path, [VALID_EXAMPLE])
        inst1 = FewShotLibrary.get_instance(library_path=lib_path)
        inst2 = FewShotLibrary.get_instance(library_path=lib_path)
        assert inst1 is inst2

    def test_reset_clears_singleton(self, tmp_path):
        from backend.agents.governance.few_shot_library import FewShotLibrary

        lib_path = _write_library(tmp_path, [VALID_EXAMPLE])
        inst1 = FewShotLibrary.get_instance(library_path=lib_path)
        FewShotLibrary.reset_instance()
        inst2 = FewShotLibrary.get_instance(library_path=lib_path)
        assert inst1 is not inst2


# ---------------------------------------------------------------------------
# FewShotLibrary Retrieval Tests
# ---------------------------------------------------------------------------


class TestFewShotLibraryRetrieval:
    """Tests for get_examples retrieval logic."""

    def setup_method(self):
        from backend.agents.governance.few_shot_library import FewShotLibrary

        FewShotLibrary.reset_instance()

    def test_returns_empty_for_unknown_scenario(self, tmp_path):
        from backend.agents.governance.few_shot_library import FewShotLibrary

        lib_path = _write_library(tmp_path, [VALID_EXAMPLE])
        lib = FewShotLibrary(library_path=lib_path)
        assert lib.get_examples("nonexistent_scenario") == []

    def test_balanced_retrieval_positive_first(self, tmp_path):
        """Positive examples must come before negative ones."""
        from backend.agents.governance.few_shot_library import FewShotLibrary

        lib_path = _write_library(tmp_path, [NEGATIVE_EXAMPLE, VALID_EXAMPLE])
        lib = FewShotLibrary(library_path=lib_path)
        examples = lib.get_examples("lead_qualification", count=2)
        assert len(examples) == 2
        assert examples[0].type == "positive"
        assert examples[1].type == "negative"

    def test_count_respected(self, tmp_path):
        from backend.agents.governance.few_shot_library import FewShotLibrary

        lib_path = _write_library(tmp_path, [VALID_EXAMPLE, NEGATIVE_EXAMPLE])
        lib = FewShotLibrary(library_path=lib_path)
        assert len(lib.get_examples("lead_qualification", count=1)) == 1

    def test_count_zero_raises(self, tmp_path):
        from backend.agents.governance.few_shot_library import FewShotLibrary

        lib_path = _write_library(tmp_path, [VALID_EXAMPLE])
        lib = FewShotLibrary(library_path=lib_path)
        with pytest.raises(ValueError, match="count must be >= 1"):
            lib.get_examples("lead_qualification", count=0)

    def test_tag_filter_includes_matching(self, tmp_path):
        from backend.agents.governance.few_shot_library import FewShotLibrary

        lib_path = _write_library(tmp_path, [VALID_EXAMPLE, NEGATIVE_EXAMPLE])
        lib = FewShotLibrary(library_path=lib_path)
        examples = lib.get_examples("lead_qualification", tags=["json_format"])
        assert len(examples) > 0

    def test_tag_filter_excludes_non_matching(self, tmp_path):
        from backend.agents.governance.few_shot_library import FewShotLibrary

        lib_path = _write_library(tmp_path, [VALID_EXAMPLE])
        lib = FewShotLibrary(library_path=lib_path)
        examples = lib.get_examples("lead_qualification", tags=["nonexistent_tag"])
        assert examples == []

    def test_only_positives_available(self, tmp_path):
        """If only positive examples exist, return them without crashing."""
        from backend.agents.governance.few_shot_library import FewShotLibrary

        lib_path = _write_library(tmp_path, [VALID_EXAMPLE])
        lib = FewShotLibrary(library_path=lib_path)
        examples = lib.get_examples("lead_qualification", count=2)
        assert len(examples) == 1
        assert examples[0].type == "positive"

    def test_only_negatives_available(self, tmp_path):
        """If only negative examples exist, return them without crashing."""
        from backend.agents.governance.few_shot_library import FewShotLibrary

        lib_path = _write_library(tmp_path, [NEGATIVE_EXAMPLE])
        lib = FewShotLibrary(library_path=lib_path)
        examples = lib.get_examples("lead_qualification", count=2)
        assert len(examples) == 1
        assert examples[0].type == "negative"


# ---------------------------------------------------------------------------
# FewShotLibrary Formatting Tests
# ---------------------------------------------------------------------------


class TestFewShotLibraryFormatting:
    """Tests for the markdown block formatting."""

    def setup_method(self):
        from backend.agents.governance.few_shot_library import FewShotLibrary

        FewShotLibrary.reset_instance()

    def test_format_block_contains_proper_action_header(self, tmp_path):
        from backend.agents.governance.few_shot_library import FewShotLibrary

        lib_path = _write_library(tmp_path, [VALID_EXAMPLE])
        lib = FewShotLibrary(library_path=lib_path)
        block = lib.format_examples_block("lead_qualification")
        assert "PROPER ACTION" in block

    def test_format_block_contains_improper_action_header(self, tmp_path):
        from backend.agents.governance.few_shot_library import FewShotLibrary

        lib_path = _write_library(tmp_path, [VALID_EXAMPLE, NEGATIVE_EXAMPLE])
        lib = FewShotLibrary(library_path=lib_path)
        block = lib.format_examples_block("lead_qualification", count=2)
        assert "IMPROPER ACTION" in block

    def test_format_block_contains_input_and_output(self, tmp_path):
        from backend.agents.governance.few_shot_library import FewShotLibrary

        lib_path = _write_library(tmp_path, [VALID_EXAMPLE])
        lib = FewShotLibrary(library_path=lib_path)
        block = lib.format_examples_block("lead_qualification")
        assert "**INPUT**:" in block
        assert "**OUTPUT**:" in block
        assert "**WHY**:" in block

    def test_format_block_contains_scenario_title(self, tmp_path):
        from backend.agents.governance.few_shot_library import FewShotLibrary

        lib_path = _write_library(tmp_path, [VALID_EXAMPLE])
        lib = FewShotLibrary(library_path=lib_path)
        block = lib.format_examples_block("lead_qualification")
        assert "Lead Qualification" in block

    def test_format_block_empty_for_unknown_scenario(self, tmp_path):
        from backend.agents.governance.few_shot_library import FewShotLibrary

        lib_path = _write_library(tmp_path, [VALID_EXAMPLE])
        lib = FewShotLibrary(library_path=lib_path)
        block = lib.format_examples_block("unknown_scenario")
        assert block == ""

    def test_format_block_contains_example_content(self, tmp_path):
        from backend.agents.governance.few_shot_library import FewShotLibrary

        lib_path = _write_library(tmp_path, [VALID_EXAMPLE])
        lib = FewShotLibrary(library_path=lib_path)
        block = lib.format_examples_block("lead_qualification")
        assert "Acme Corp" in block
        assert "proper action" in block.lower()


# ---------------------------------------------------------------------------
# assemble_prompt Integration Tests
# ---------------------------------------------------------------------------


class TestAssemblePromptIntegration:
    """Tests for the assemble_prompt integration with few-shot injection."""

    def setup_method(self):
        from backend.agents.governance.few_shot_library import FewShotLibrary

        FewShotLibrary.reset_instance()

    def test_no_scenario_returns_preamble_only(self):
        from backend.agents.governance.pride_kernel import assemble_prompt

        result = assemble_prompt("You are an analyst.")
        assert "CITADEL GOVERNANCE" in result
        assert "You are an analyst." in result
        assert "PROPER ACTION" not in result

    def test_with_scenario_injects_examples(self, tmp_path):
        from backend.agents.governance.few_shot_library import FewShotLibrary
        from backend.agents.governance.pride_kernel import assemble_prompt

        lib_path = _write_library(tmp_path, [VALID_EXAMPLE, NEGATIVE_EXAMPLE])
        FewShotLibrary.get_instance(library_path=lib_path)

        result = assemble_prompt("You are an analyst.", scenario="lead_qualification")
        assert "CITADEL GOVERNANCE" in result
        assert "PROPER ACTION" in result
        assert "IMPROPER ACTION" in result
        assert "You are an analyst." in result

    def test_prompt_order_preamble_then_examples_then_role(self, tmp_path):
        """The preamble must come before examples, which come before the role prompt."""
        from backend.agents.governance.few_shot_library import FewShotLibrary
        from backend.agents.governance.pride_kernel import assemble_prompt

        lib_path = _write_library(tmp_path, [VALID_EXAMPLE, NEGATIVE_EXAMPLE])
        FewShotLibrary.get_instance(library_path=lib_path)

        result = assemble_prompt("ROLE_MARKER", scenario="lead_qualification")
        preamble_pos = result.find("CITADEL GOVERNANCE")
        examples_pos = result.find("PROPER ACTION")
        role_pos = result.find("ROLE_MARKER")

        assert preamble_pos < examples_pos < role_pos

    def test_missing_library_degrades_gracefully(self):
        """If the library file is missing, assemble_prompt must not raise."""
        from backend.agents.governance.few_shot_library import FewShotLibrary
        from backend.agents.governance.pride_kernel import assemble_prompt

        # Patch get_instance to raise FileNotFoundError, simulating a missing file.
        # This is the correct target: the call site inside assemble_prompt.
        with patch.object(
            FewShotLibrary,
            "get_instance",
            side_effect=FileNotFoundError("Library file not found"),
        ):
            FewShotLibrary.reset_instance()
            # Should not raise — should degrade gracefully
            result = assemble_prompt("You are an analyst.", scenario="lead_qualification")
            assert "CITADEL GOVERNANCE" in result
            assert "You are an analyst." in result
            assert "PROPER ACTION" not in result

    def test_no_scenario_no_few_shot_block(self):
        from backend.agents.governance.pride_kernel import assemble_prompt

        result = assemble_prompt("You are an analyst.")
        assert "Reference Examples" not in result

    def test_few_shot_count_respected(self, tmp_path):
        """few_shot_count=1 should inject at most 1 example."""
        from backend.agents.governance.few_shot_library import FewShotLibrary
        from backend.agents.governance.pride_kernel import assemble_prompt

        lib_path = _write_library(tmp_path, [VALID_EXAMPLE, NEGATIVE_EXAMPLE])
        FewShotLibrary.get_instance(library_path=lib_path)

        result = assemble_prompt(
            "You are an analyst.",
            scenario="lead_qualification",
            few_shot_count=1,
        )
        # With count=1, only the positive example should be present
        assert "PROPER ACTION" in result
        assert "IMPROPER ACTION" not in result


# ---------------------------------------------------------------------------
# Real Library Integration Tests
# ---------------------------------------------------------------------------


class TestRealLibraryIntegration:
    """
    Tests against the actual few_shot_library.json file in the repo.
    These tests validate the content and structure of the production library.
    """

    def setup_method(self):
        from backend.agents.governance.few_shot_library import FewShotLibrary

        FewShotLibrary.reset_instance()

    def test_real_library_loads(self):
        from backend.agents.governance.few_shot_library import FewShotLibrary

        lib = FewShotLibrary.get_instance()
        assert len(lib._examples) > 0

    def test_real_library_has_all_four_scenarios(self):
        from backend.agents.governance.few_shot_library import FewShotLibrary

        lib = FewShotLibrary.get_instance()
        scenarios = lib.list_scenarios()
        assert "lead_qualification" in scenarios
        assert "lead_discovery" in scenarios
        assert "proposal_writing" in scenarios
        assert "workforce_planning" in scenarios

    def test_every_scenario_has_positive_and_negative(self):
        from backend.agents.governance.few_shot_library import FewShotLibrary

        lib = FewShotLibrary.get_instance()
        for scenario in lib.list_scenarios():
            examples = lib.get_examples(scenario, count=4)
            types = {e.type for e in examples}
            assert "positive" in types, f"{scenario} has no positive examples"
            assert "negative" in types, f"{scenario} has no negative examples"

    def test_all_examples_have_non_empty_explanations(self):
        from backend.agents.governance.few_shot_library import FewShotLibrary

        lib = FewShotLibrary.get_instance()
        for ex in lib._examples:
            assert (
                len(ex.explanation) > 50
            ), f"Explanation too short for {ex.scenario}/{ex.type}: {ex.explanation!r}"

    def test_lead_qualification_examples_contain_json(self):
        """The qualification output examples must be valid JSON."""
        import json as _json
        from backend.agents.governance.few_shot_library import FewShotLibrary

        lib = FewShotLibrary.get_instance()
        for ex in lib.get_examples("lead_qualification", count=4):
            try:
                parsed = _json.loads(ex.output)
                assert isinstance(parsed, dict)
            except _json.JSONDecodeError as e:
                pytest.fail(
                    f"lead_qualification {ex.type} output is not valid JSON: {e}\n{ex.output}"
                )
