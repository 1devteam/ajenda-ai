import json
from types import SimpleNamespace

from backend.services.mission_composition.coverage import assess_coverage
from backend.services.mission_composition.intent_interpreter import interpret_instruction
from scripts.validation import api_mission_proof_suite
from scripts.validation.api_mission_proof_artifact import (
    canonical_payload_digest,
    verify_integrity,
    with_integrity,
    write_manifest,
)
from scripts.validation.api_mission_proof_suite import FIXTURE_INSTRUCTIONS, FIXTURE_LANES, _proof_client_ip


def test_proof_artifact_digest_covers_payload_not_its_own_integrity() -> None:
    payload = {"schema_version": 1, "results": [{"mission_id": "mission-a", "status": "passed"}]}

    artifact = with_integrity(payload)

    assert verify_integrity(artifact) is True
    assert artifact["integrity"]["payload_sha256"] == canonical_payload_digest(payload)
    artifact["results"][0]["status"] = "failed"
    assert verify_integrity(artifact) is False


def test_write_manifest_produces_verifiable_json(tmp_path) -> None:
    path = tmp_path / "run" / "manifest.json"

    artifact = write_manifest(path, {"schema_version": 1, "results": []})

    assert path.exists()
    assert verify_integrity(artifact) is True


def test_every_fixture_proof_lane_has_supported_fixture_scope() -> None:
    assert tuple(lane.instruction for lane in FIXTURE_LANES) == FIXTURE_INSTRUCTIONS
    for lane in FIXTURE_LANES:
        assessment = assess_coverage(interpret_instruction(lane.instruction))

        assert lane.industry and lane.location
        assert assessment.mode == "local_fixture", lane.instruction
        assert assessment.ready is True, lane.instruction


def test_fixture_proof_client_identity_is_stable_per_lane_and_unique_per_run() -> None:
    first = _proof_client_ip(run_id="run-a", lane=1)

    assert first == _proof_client_ip(run_id="run-a", lane=1)
    assert first != _proof_client_ip(run_id="run-b", lane=1)
    assert first != _proof_client_ip(run_id="run-a", lane=2)
    assert first.startswith("198.18.")


def test_fixture_lane_passes_declared_scope_to_public_operator_proof(monkeypatch, tmp_path) -> None:
    observed_environment: dict[str, str] = {}

    def fake_run(*_args, **kwargs):
        environment = kwargs["env"]
        observed_environment.update(environment)
        evidence_path = tmp_path / "lane-01-runtime-evidence.json"
        reconciliation_path = tmp_path / "lane-01-runtime-reconciliation.json"
        evidence_path.write_text(json.dumps({"mission_id": "mission-1"}), encoding="utf-8")
        reconciliation_path.write_text(json.dumps({"mission_id": "mission-1", "provenance": {}}), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout=json.dumps({"mission_id": "mission-1"}), stderr="")

    monkeypatch.setattr(api_mission_proof_suite.subprocess, "run", fake_run)

    result = api_mission_proof_suite._run_lane(
        run_dir=tmp_path,
        run_id="run-1",
        lane=1,
        instruction="Find three HVAC companies in Dallas using local fixture data only.",
        mode="fixture",
        fixture_industry="HVAC",
        fixture_location="Dallas",
    )

    assert result["status"] == "passed"
    assert observed_environment["AJENDA_OPERATOR_PROOF_FIXTURE_INDUSTRY"] == "HVAC"
    assert observed_environment["AJENDA_OPERATOR_PROOF_FIXTURE_LOCATION"] == "Dallas"
