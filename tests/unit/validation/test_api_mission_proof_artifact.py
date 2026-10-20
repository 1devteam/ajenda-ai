from backend.services.mission_composition.coverage import assess_coverage
from backend.services.mission_composition.intent_interpreter import interpret_instruction
from scripts.validation.api_mission_proof_artifact import (
    canonical_payload_digest,
    verify_integrity,
    with_integrity,
    write_manifest,
)
from scripts.validation.api_mission_proof_suite import FIXTURE_INSTRUCTIONS, _proof_client_ip


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
    for instruction in FIXTURE_INSTRUCTIONS:
        assessment = assess_coverage(interpret_instruction(instruction))

        assert assessment.mode == "local_fixture", instruction
        assert assessment.ready is True, instruction


def test_fixture_proof_client_identity_is_stable_per_lane_and_unique_per_run() -> None:
    first = _proof_client_ip(run_id="run-a", lane=1)

    assert first == _proof_client_ip(run_id="run-a", lane=1)
    assert first != _proof_client_ip(run_id="run-b", lane=1)
    assert first != _proof_client_ip(run_id="run-a", lane=2)
    assert first.startswith("198.18.")
