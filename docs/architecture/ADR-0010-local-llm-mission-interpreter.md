# ADR-0010: Local LLM Mission Interpreter

- **Status:** Accepted
- **Date:** 2026-08-03
- **Owner:** AJENDA-AI Architecture Team
- **Related:** ADR-0001, ADR-0003, ADR-0008, ADR-0009

## Context

The deterministic mission interpreter accumulated spelling correction, fuzzy matching, fixed phrase aliases, clause parsing, and special cases. It remained weak at broken language and shorthand while growing into a second, brittle language system. Ajenda already has authoritative deterministic layers for policy, permissions, job routing, ability selection, credentials, graph compilation, runtime admission, queueing, leases, tools, and evidence. A language model must not duplicate or bypass them.

## Decision

Replace the phrase-heavy mission interpreter with one small local model behind an internal OpenAI-compatible adapter. This is a replacement interpreter, not parallel “mission intelligence.” Its entire responsibility is:

```text
broken or shorthand human wording
  → faithful, coherent, schema-constrained MissionIntent candidate
```

The initial default is the 4B instruction model `qwen3:4b-instruct-2507-q4_K_M`. The transport remains runner-agnostic so Ollama, llama.cpp, or another private OpenAI-compatible service can satisfy the same contract.

### Authority and data boundary

- Input is the exact user instruction plus an allowlisted subset of approved business-profile facts.
- Output is strict JSON validated by Pydantic. Unknown fields are rejected.
- Every material outcome, policy, target, context requirement, constraint, timing value, success criterion, and instruction segment carries source grounding. Target kinds and context requirements use closed vocabularies; the model cannot add arbitrary target attributes.
- A deterministic meaning guard rejects invented email addresses, URLs, quantities, and ungrounded fields.
- The model never chooses jobs, abilities, tools, credentials, permissions, policy, approval, queue state, or runtime actions.
- Raw prompts and model output are never written to application logs. The durable proposal remains tenant-scoped and retains the raw instruction for backend audit. Browser-visible mission lifecycle metadata stores only the confirmed interpretation and a sanitized intent without raw/source evidence spans.

### Human review contract

Compose calls the model once, validates the candidate, then runs Ajenda’s existing deterministic job, resolver, charter, credential, and graph-preview layers. The frontend shows only the model’s interpretation as the language echo, plus all model-derived details that can affect composition (outcomes, quantity, targets, policies, timing, context sources, limits, and exclusions). It does not add a second echo of the original instruction.

The user must explicitly acknowledge that the displayed interpretation matches their intent. Confirmation sends the proposal ID and interpretation fingerprint. The backend:

1. loads and row-locks the tenant-scoped durable server proposal,
2. requires the explicit acknowledgement,
3. verifies the exact fingerprint and stored record integrity,
4. reruns current deterministic governance and compilation from the stored intent,
5. creates mission intake, plan, and draft graph only.

Confirmation and later compile never call the model. A changed request must return through compose and human review. This prevents nondeterministic interpretation drift after the user has reviewed the wording. The acknowledgement is a semantic check, not a replacement for Ajenda’s authorization or runtime gates.

The fingerprint covers the same execution-relevant interpretation projection displayed to the user. Proposal creation fails if that projection cannot be stored durably. Confirmation is proposal-idempotent across retry keys: the database row lock and stored receipt prevent two workers from creating duplicate missions.

### Failure and rollback

Transport timeout, unavailable service, invalid JSON, schema mismatch, ungrounded output, protected-fact invention, and proposal-store failure all fail closed with structured errors. There is no template, fuzzy, or legacy parser fallback.

`AJENDA_MISSION_INTERPRETER_ENABLED=false` is the rollback switch. It disables new composition with a structured 503 while confirmed missions continue through deterministic compile and runtime layers. Legacy missions without a stored confirmed intent must be planned again before server recompilation; the backend will not silently reinterpret them.

## Consequences

### Positive

- Broken language, shorthand, and misspellings are handled by a component designed for language without expanding its authority.
- The 1,000+ line phrase interpreter and optional spelling/fuzzy pipeline are removed.
- Exact review fingerprints and durable proposal locks close compose/confirm drift and duplicate-confirm windows.
- Runner outages and model failures are visible instead of producing synthetic or guessed plans.

### Tradeoffs

- New mission composition depends on a local model endpoint when enabled.
- Operators must provision model memory, preload the model, and monitor latency.
- Schema or prompt changes require compatibility tests and should bump their versions.
- Existing unconfirmed/legacy proposals cannot be upgraded into confirmed interpretations without a new compose cycle.

## Verification

- Unit: strict schema, prompt-as-data isolation, timeout/invalid-output failures, grounding, invented fact rejection, ambiguity, and readiness.
- Composition: the model cannot inject actions; charter, credentials, resolver, and compiler remain authoritative.
- Contract: compose exposes the interpretation, review details, and fingerprint but not the raw instruction/full server record; confirmation rejects missing acknowledgement or fingerprint mismatch, is proposal-idempotent, and creates no queue state.
- Compile: stored confirmed intent is required; changed instructions are rejected; no model call occurs.
- Frontend: the review card contains only the interpretation and its derived details (never a second raw-input echo), start remains locked until acknowledgement, and cancel creates nothing.
- Deployment: disabled-by-default configuration, conditional production validation, documented local runner, and fail-closed rollback.
