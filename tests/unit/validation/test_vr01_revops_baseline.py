from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.validation.vr01_revops_baseline import DEFAULT_CORPUS, run


def test_vr01_corpus_has_required_scenario_classes() -> None:
    payload = json.loads(DEFAULT_CORPUS.read_text(encoding="utf-8"))
    scenarios = {case["scenario"] for case in payload["cases"]}
    assert {
        "direct_draft_only",
        "paraphrase",
        "conditional_external_effects",
        "missing_information",
        "unsupported_request",
        "prompt_injection",
        "contradiction",
        "missing_provider",
        "connected_system_read_missing",
        "long_context_prohibition",
    } <= scenarios


def test_vr01_runner_is_non_authoritative_and_passes_declared_expectations(tmp_path: Path) -> None:
    report = run(DEFAULT_CORPUS)
    assert report["authority"] == "evaluation_only"
    assert report["grants_execution_authority"] is False
    assert isinstance(report["worktree_dirty"], bool)
    assert report["corpus_kind"] == "development"
    assert report["corpus_sealed"] is False
    assert report["corpus_sha256"].startswith("sha256:")
    assert report["summary"]["cases"] == 10
    assert report["summary"]["passed"] == 10
    assert report["summary"]["failed"] == 0
    assert "external_effect_safety" in report["not_measured"]
    by_id = {item["case_id"]: item for item in report["results"]}
    assert by_id["dev-contradiction-007"]["checks"]["clarification"] is True
    assert by_id["dev-long-context-010"]["observed"]["proposal_status"] == "interpretation_failed"


def test_held_out_corpus_requires_seal_and_expected_hash(tmp_path: Path) -> None:
    payload = json.loads(DEFAULT_CORPUS.read_text(encoding="utf-8"))
    payload.update({"corpus_id": "revops-held-out-v1", "corpus_kind": "held_out", "sealed": True})
    corpus = tmp_path / "held-out.json"
    corpus.write_text(json.dumps(payload), encoding="utf-8")

    try:
        run(corpus)
    except ValueError as exc:
        assert "expected sha256" in str(exc)
    else:
        raise AssertionError("held-out corpus ran without sealed hash verification")

    digest = f"sha256:{hashlib.sha256(corpus.read_bytes()).hexdigest()}"
    report = run(corpus, expected_corpus_sha256=digest)
    assert report["corpus_kind"] == "held_out"
    assert report["corpus_sealed"] is True
    assert report["corpus_path"] == "<external>/held-out.json"


def test_sealed_corpus_hash_mismatch_fails_closed() -> None:
    try:
        run(DEFAULT_CORPUS, expected_corpus_sha256="sha256:" + ("0" * 64))
    except ValueError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("corpus hash mismatch was accepted")
