from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[3] / "scripts/validation/graph_mission_instance_integrity.py"
SPEC = importlib.util.spec_from_file_location("ajenda_graph_mission_instance_integrity", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _codes(report: dict[str, object]) -> set[str]:
    return {str(item["code"]) for item in report["findings"]}


def test_failed_ui_mission_slice_surfaces_cross_layer_findings() -> None:
    report = MODULE.evaluate_mission_instance(
        {
            "instruction": (
                "> Research competitors.\n"
                "> Do not contact anyone. Produce a comparison table and highlight market opportunities."
            ),
            "objective": "> Research competitors. Do not contact anyone. Produce a comparison tab...",
            "mission_status": "running",
            "task_graph": {
                "nodes": [
                    {
                        "key": "ability-web-research",
                        "metadata": {"job_key": "research.discover_prospects"},
                        "output_contract": {"artifact": "prospect_candidates"},
                    },
                    {
                        "key": "ability-provider-external_read",
                        "metadata": {"job_key": "ops.google_contacts_read"},
                        "output_contract": {"artifact": "contact_records"},
                    },
                ]
            },
            "task_results": [
                {"task_id": "research", "status": "completed"},
                {
                    "task_id": "contacts",
                    "status": "failed",
                    "failure": "Failed to decrypt runtime credential ciphertext.",
                },
            ],
        }
    )

    assert report["status"] == "blocked"
    assert _codes(report) == {
        "mission_credential.runtime_secret_mismatch",
        "mission_deliverable.report_not_materialized",
        "mission_input.markdown_quote_leaked",
        "mission_input.objective_truncated",
        "mission_selection.unsupported_google_contacts",
        "mission_state.terminal_tasks_active_mission",
    }


def test_coherent_research_report_slice_is_clear() -> None:
    report = MODULE.evaluate_mission_instance(
        {
            "instruction": "Research competitors and produce a comparison report.",
            "objective": "Research competitors and produce a comparison report.",
            "mission_status": "completed",
            "task_graph": {
                "nodes": [
                    {
                        "key": "research",
                        "metadata": {"job_key": "research.discover_prospects"},
                        "output_contract": {"artifact": "prospect_candidates"},
                    },
                    {
                        "key": "report",
                        "metadata": {"job_key": "research.synthesize_report"},
                        "output_contract": {"artifact": "research_report"},
                    },
                ]
            },
            "task_results": [
                {"task_id": "research", "status": "completed"},
                {"task_id": "report", "status": "completed"},
            ],
        }
    )

    assert report["status"] == "clear"
    assert report["findings"] == []
    assert report["policy"] == {"enforcement": "diagnostic", "executes_work": False, "mutates_runtime": False}


def test_explicit_google_contacts_request_is_not_rejected_as_irrelevant() -> None:
    report = MODULE.evaluate_mission_instance(
        {
            "instruction": "Read my Google Contacts.",
            "objective": "Read my Google Contacts.",
            "mission_status": "completed",
            "task_graph": {
                "nodes": [
                    {
                        "key": "contacts",
                        "metadata": {"job_key": "ops.google_contacts_read"},
                        "output_contract": {"artifact": "contact_records"},
                    }
                ]
            },
            "task_results": [{"task_id": "contacts", "status": "completed"}],
        }
    )

    assert "mission_selection.unsupported_google_contacts" not in _codes(report)
