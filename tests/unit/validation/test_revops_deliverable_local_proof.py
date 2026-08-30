from __future__ import annotations

import subprocess
from pathlib import Path

PROOF_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "dev" / "revops-deliverable-local-proof.sh"


def test_revops_deliverable_local_proof_has_valid_shell_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(PROOF_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_revops_deliverable_local_proof_is_effect_free_and_targets_required_surfaces() -> None:
    script = PROOF_SCRIPT.read_text(encoding="utf-8")

    assert 'AJENDA_ENV="test"' in script
    assert 'AJENDA_ALLOW_SIMULATED_EXTERNAL="false"' in script
    assert "test_revops_mission_deliverable.py" in script
    assert "test_mission_deliverable_route.py" in script
    assert "test_execution_task_repository.py" in script
    assert "test_gtm_email_send_review_block_emits_canonical_attempt_artifact" in script
    assert "test_gtm_email_send_uses_network_egress_for_real_send" in script
