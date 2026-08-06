# Wave A remote status (2026-08-06)

## PR
https://github.com/1devteam/ajenda-ai/pull/405
Branch: `feat/composition-operator-reads-wave-a`

## On remote tip
- job_catalog (3 Wave A jobs)
- ability_vocab
- connector_capabilities (github row)
- **capability_resolver** (Wave A preferences + connection hints) ✅
- readiness (external_risk)
- operating_charter (may_prepare)
- tests/unit/services/test_composition_operator_reads.py (10 cases)
- ADR-0008 touch
- APPLY_WAVE_A.sh (rejects placeholder)

## Still missing (required before merge)
- contracts.py (outcomes + versions 5/8/5)
- action_inputs.py (profile/repo/People API bindings)
- intent_interpreter.py (read patterns, entity extract, success criteria)

## Authoritative complete sources
Workspace: `/home/workdir/artifacts/wave-a/{contracts,action_inputs,intent_interpreter}.py`

## Finish (authenticated local)
```bash
git fetch origin feat/composition-operator-reads-wave-a
git checkout feat/composition-operator-reads-wave-a
# copy contracts.py action_inputs.py intent_interpreter.py from workspace artifacts/wave-a/
# into backend/services/mission_composition/
pytest tests/unit/services/test_composition_operator_reads.py -q
git add backend/services/mission_composition/{contracts,action_inputs,intent_interpreter}.py
git commit -m "feat(composition): Wave A contracts + action_inputs + intent_interpreter"
git push
```

## Pride note
Do not merge until JOB_CATALOG=5 / INTERPRETER=8 / RESOLVER=5 and the three missions compose.
