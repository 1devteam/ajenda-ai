# Wave A remote status (2026-08-06)

## PR
https://github.com/1devteam/ajenda-ai/pull/405
Branch: `feat/composition-operator-reads-wave-a`

## On remote tip
- job_catalog (3 Wave A jobs)
- ability_vocab
- connector_capabilities (github row)
- readiness (external_risk)
- operating_charter (may_prepare)
- tests/unit/services/test_composition_operator_reads.py (10 cases)
- ADR-0008 touch
- APPLY_WAVE_A.sh (rejects placeholder)

## Missing on remote (matrix incomplete without these)
- contracts.py (outcomes + versions 5/8/5)
- capability_resolver.py (action preference + connection hints)
- action_inputs.py (profile/repo/People API bindings)
- intent_interpreter.py (read patterns, entity extract, success criteria)

## Authoritative complete sources
All four live under workspace `artifacts/wave-a/` and the full unified patch:
`artifacts/wave-a/0001-feat-composition-Wave-A-operator-reads-LinkedIn-GitH.patch`

## One-shot finish (authenticated local)
```bash
git fetch origin feat/composition-operator-reads-wave-a
git checkout feat/composition-operator-reads-wave-a
# Copy complete sources from artifacts/wave-a/ into
# backend/services/mission_composition/{contracts,capability_resolver,action_inputs,intent_interpreter}.py
pytest tests/unit/services/test_composition_operator_reads.py -q
```

## Pride note
Process was full-matrix, tested locally (15 Wave A + 60 regression).
Remote tip is partial until the four large composition sources land.
Do not merge until versions assert JOB_CATALOG=5 / INTERPRETER=8 / RESOLVER=5.
