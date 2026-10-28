# Codex first-wave evidence — C01, C02, C03, C09

Baseline and implementation work were performed on
`rebuild/public-research-evidence-first` at
`428d7df396950704f9868ffcd0a410e9934a4855` before this working-tree diff.

## Baseline

```text
python -m pytest tests/unit/internet/test_page_read.py tests/unit/tools/test_web_actions.py -q
21 passed

python -m pytest tests/simulation/causal_public_research_invariants.py -q -rA \
  --junitxml=/tmp/ajenda-public-research-baseline.xml
3 passed, 7 failed
```

The seven baseline failures were SIM-01, SIM-03, SIM-04, SIM-05, SIM-06,
SIM-07, and SIM-09. SIM-03 is C05, which is deliberately not part of this
first wave.

## First-wave result

```text
python -m pytest \
  tests/unit/tools/test_web_actions.py \
  tests/unit/tools/test_contact_observation.py \
  tests/unit/tools/test_local_fixture_contact_observation.py \
  tests/unit/tools/test_sales_actions.py \
  tests/unit/services/test_mission_input_binding.py \
  tests/unit/services/test_mission_composition_engine.py \
  tests/unit/services/test_mission_contacts_clause.py \
  tests/unit/services/test_observe_contacts_compile.py -q
173 passed

python -m pytest tests/simulation/causal_public_research_invariants.py -q -rA \
  --junitxml=/tmp/ajenda-public-research-wave1.xml
9 passed, 1 failed (SIM-03 / C05, intentionally unresolved)
```

The corrected cases are C01/SIM-04, C02/SIM-05 and SIM-06, C03/SIM-01,
SIM-02, and SIM-09, and C09/SIM-07. The new binding proof confirms that a
public qualification receives the verifier's `verified_prospect_candidates`,
not raw discovery candidates or a synthesized market-company seed.

## Scope and deferred dependency

C02 deliberately stays fail-closed when a composed qualification has no
upstream prospect records. The action itself now returns zero scored rows when
invoked with such a bounded input, but the existing runtime binder still
rejects an absent required upstream collection. That valid-empty lifecycle is
C07 and was not relaxed in this wave: a provider failure, missing output, or
malformed output must not become a successful empty discovery result.

No C05 identity-policy, C04/C08 search-provider, C07 valid-empty lifecycle,
or browser/network ownership code was changed here.
