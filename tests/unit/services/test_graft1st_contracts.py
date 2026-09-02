from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.services.tools.schemas import SideEffectClass
from backend.services.vertical_ops.graft1st_contracts import (
    GRAFT1ST_REQUIRED_NODE_KEYS,
    CanonicalContractPackage,
    EffectCertainty,
    EffectReceiptContract,
    IdentityDecisionStatus,
    IdentityMatchDecision,
    InterminglingSimulationSuite,
    SideEffectAuthorizationContract,
    assert_compatible_contract_version,
)

FIXTURE = Path(__file__).parents[2] / "fixtures" / "graft1st" / "gtm_crm_communications_contract_package.v2.json"
SIMULATION_FIXTURE = Path(__file__).parents[2] / "fixtures" / "graft1st" / "intermingling_simulations.v1.json"


def _fixture_payload() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_locked_contract_package_fixture_is_valid_and_declarative() -> None:
    package = CanonicalContractPackage.model_validate(_fixture_payload())

    assert package.package_version == "2.0.0"
    assert package.authority_class == "declarative"
    assert package.grants_execution_authority is False
    assert all(node.grants_execution_authority is False for node in package.nodes)
    assert {node.node_key for node in package.nodes} == GRAFT1ST_REQUIRED_NODE_KEYS


def test_contract_package_rejects_unknown_node_and_artifact_mismatch() -> None:
    unknown = _fixture_payload()
    unknown["edges"][0]["dependency_node_key"] = "missing.node"  # type: ignore[index]
    with pytest.raises(ValidationError, match="unknown node"):
        CanonicalContractPackage.model_validate(unknown)

    mismatch = _fixture_payload()
    mismatch["edges"][0]["artifact_type"] = "UndeclaredArtifact"  # type: ignore[index]
    with pytest.raises(ValidationError, match="not produced"):
        CanonicalContractPackage.model_validate(mismatch)


def test_contract_package_rejects_duplicate_nodes_and_hard_cycles() -> None:
    duplicate = _fixture_payload()
    duplicate["nodes"].append(deepcopy(duplicate["nodes"][0]))  # type: ignore[union-attr,index]
    with pytest.raises(ValidationError, match="node keys must be unique"):
        CanonicalContractPackage.model_validate(duplicate)

    cycle = _fixture_payload()
    cycle["nodes"][0]["accepts"] = ["VerticalSelection"]  # type: ignore[index]
    cycle["edges"].append(  # type: ignore[union-attr]
        {
            "edge_id": "E99",
            "consumer_node_key": "mission.interpret",
            "dependency_node_key": "vertical.select",
            "artifact_type": "VerticalSelection",
            "artifact_schema_version": "1.0.0",
            "dependency_kind": "hard",
            "semantics": "requires",
            "applicability_predicate": None,
            "adjudication_requirement": "Synthetic cycle fixture.",
        }
    )
    with pytest.raises(ValidationError, match="hard dependencies contain a cycle"):
        CanonicalContractPackage.model_validate(cycle)


def test_contract_package_rejects_incomplete_frozen_node_registry() -> None:
    incomplete = _fixture_payload()
    incomplete["nodes"].pop()  # type: ignore[union-attr]
    with pytest.raises(ValidationError, match="canonical node registry mismatch"):
        CanonicalContractPackage.model_validate(incomplete)


def test_contract_major_version_fails_closed() -> None:
    assert_compatible_contract_version(declared="2.7.3", supported_major=2)
    with pytest.raises(ValueError, match="unsupported contract major version"):
        assert_compatible_contract_version(declared="3.0.0", supported_major=2)
    with pytest.raises(ValueError, match="invalid semantic contract version"):
        assert_compatible_contract_version(declared="latest", supported_major=2)


def test_ambiguous_identity_cannot_select_canonical_entity() -> None:
    with pytest.raises(ValidationError, match="cannot select a canonical entity"):
        IdentityMatchDecision(
            decision_status=IdentityDecisionStatus.AMBIGUOUS,
            candidate_ids=("candidate-1", "candidate-2"),
            canonical_entity_id="entity-1",
            conflicting_evidence_ids=("evidence-1",),
            rule_version="1.0.0",
            decided_by="identity.resolve_company",
        )


def test_effect_authorization_is_payload_bound_and_expires_after_issue() -> None:
    now = datetime.now(UTC)
    authorization = SideEffectAuthorizationContract(
        tenant_id="tenant-1",
        reviewer_principal_id="reviewer-1",
        task_id="task-1",
        action_name="facebook.publish",
        capability_id="capability-1",
        adapter_id="adapter-1",
        payload_hash="sha256:" + "a" * 64,
        destination="facebook-page-1",
        side_effect_class=SideEffectClass.EXTERNAL_PUBLISH,
        issued_at=now,
        expires_at=now + timedelta(minutes=10),
    )
    assert authorization.single_use is True

    with pytest.raises(ValidationError, match="must be after issued_at"):
        authorization.model_copy(update={"expires_at": now - timedelta(seconds=1)}).model_dump()
        SideEffectAuthorizationContract.model_validate(
            {**authorization.model_dump(), "expires_at": now - timedelta(seconds=1)}
        )


def test_verified_effect_requires_provider_identity_and_readback() -> None:
    now = datetime.now(UTC)
    base = {
        "provider": "youtube",
        "provider_account_id": "channel-1",
        "action_name": "youtube.publish_video",
        "idempotency_key": "effect-1",
        "request_hash": "sha256:" + "b" * 64,
        "attempted_at": now,
        "certainty": EffectCertainty.VERIFIED,
    }
    with pytest.raises(ValidationError, match="read-back proof"):
        EffectReceiptContract.model_validate(base)

    receipt = EffectReceiptContract.model_validate(
        {
            **base,
            "provider_object_ids": ["video-1"],
            "read_back_at": now + timedelta(seconds=1),
            "read_back_hash": "sha256:" + "c" * 64,
        }
    )
    assert receipt.certainty == EffectCertainty.VERIFIED


def test_intermingling_simulation_suite_has_ordered_shared_state() -> None:
    suite = InterminglingSimulationSuite.model_validate_json(SIMULATION_FIXTURE.read_text(encoding="utf-8"))
    assert len(suite.scenarios) == 5


def test_intermingling_simulation_rejects_unordered_shared_write() -> None:
    payload = json.loads(SIMULATION_FIXTURE.read_text(encoding="utf-8"))
    scenario = payload["scenarios"][0]
    scenario["steps"][0]["state_access"] = [{"resource_key": "entity:collision", "mode": "write"}]
    scenario["steps"][1]["state_access"] = [{"resource_key": "entity:collision", "mode": "write"}]
    with pytest.raises(ValidationError, match="unordered simulation state collision"):
        InterminglingSimulationSuite.model_validate(payload)
