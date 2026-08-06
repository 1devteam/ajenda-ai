# Wave A remote status

Branch: `feat/composition-operator-reads-wave-a`
PR: https://github.com/1devteam/ajenda-ai/pull/405

## On remote (composition matrix)
- job_catalog (3 Wave A jobs)
- ability_vocab
- connector_capabilities (github)
- capability_resolver (prefs + connection hints) ✅
- readiness, operating_charter, tests, ADR

## Apply on local after pull

```bash
cd ~/projects/ajenda-ai
git pull --ff-only origin feat/composition-operator-reads-wave-a

# 1) contracts versions + outcomes
bash artifacts/wave-a/APPLY_CONTRACTS.sh
# or: git apply --index artifacts/wave-a/contracts_wave_a.patch

# 2) action_inputs handlers
python3 artifacts/wave-a/install_action_inputs_wave_a.py

# 3) intent_interpreter — still pending (next push)

# 4) verify
PYTHONPATH=. pytest tests/unit/services/test_composition_operator_reads.py -q
git add -A && git status
git commit -m "feat(composition): Wave A contracts + action_inputs applied"
git push
```

## Remaining
- intent_interpreter.py Wave A patterns (next)
