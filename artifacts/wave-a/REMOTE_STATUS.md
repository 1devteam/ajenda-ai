# Wave A — apply on local after pull

Branch: `feat/composition-operator-reads-wave-a`  
PR: https://github.com/1devteam/ajenda-ai/pull/405

## Already on remote tip
- job_catalog, ability_vocab, connector_capabilities
- capability_resolver (Wave A prefs + connection hints)
- readiness, operating_charter, tests, ADR

## Apply the three remaining sources (from artifacts)

```bash
cd ~/projects/ajenda-ai
git pull --ff-only origin feat/composition-operator-reads-wave-a

# 1) contracts — versions 5/8/5 + read_linkedin/github/contacts
bash artifacts/wave-a/APPLY_CONTRACTS.sh
# equivalent: git apply --index artifacts/wave-a/contracts_wave_a.patch

# 2) action_inputs — LinkedIn / GitHub / People API handlers
python3 artifacts/wave-a/install_action_inputs_wave_a.py

# 3) intent_interpreter — read patterns + outcome assembly
python3 artifacts/wave-a/install_intent_interpreter_wave_a.py

# 4) verify
PYTHONPATH=. pytest tests/unit/services/test_composition_operator_reads.py -q

# 5) commit + push
git add backend/services/mission_composition/{contracts,action_inputs,intent_interpreter}.py
git status
git commit -m "feat(composition): Wave A contracts + action_inputs + intent_interpreter"
git push origin feat/composition-operator-reads-wave-a
```

## Pride note
Full matrix was tested in workspace. Remote tip ships apply scripts because
large single-file MCP pushes were truncating; surgical patches are complete.
