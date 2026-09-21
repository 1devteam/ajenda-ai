# Mission verification wrap-up — 2026-09-21

This record closes the current Ajenda runtime verification pass before the web
work pivot. It is an evidence summary, not a claim that public search or
advisory missions are production-complete.

## Scope

Two ten-mission matrices used the public API path: signup, verification,
bootstrap-key promotion, composition, confirmation, one server launch, Redis,
WorkerLoop, task dispatch, evidence, and the deliverable read endpoint.

The durable mission records and task outputs remain the source of truth. The
local summaries are `/tmp/ajenda-multi-results.json` and
`/tmp/ajenda-multi-results-2.json`.

## Verified outcomes

- The internal CRM RevOps path completed with persisted prospects, evidence,
  qualification, and drafts without sending.
- The public cleaning RevOps path completed after the per-artifact quantity
  correction: four research rows, two qualified rows, two drafts, five
  evidence records, and a complete deliverable.
- The internal CRM readback/ranking path completed with three persisted rows.
- CRM writes and public-to-CRM persistence stopped at the existing human-review
  gate. No external CRM mutation was performed.
- Public missions with too few verified identities failed closed. Directory
  pages and unresolved identities did not become prospects.
- Representative completed and failed missions had released worker leases;
  no live queue backlog remained after the run. Dead-letter entries preserve
  failed work for review.

## Fixes completed in this pass

- Deliverable row requirements are now carried per artifact. Research quantity
  no longer incorrectly applies to qualification and draft artifacts.
- Mission rollup now fails when all tasks are terminal but the durable
  deliverable remains incomplete.
- Read paths reconcile missions that have only `pending_review` tasks to
  `paused`, so an approval hold is not presented as active execution.

## Explicit remaining boundaries

- Free public search cannot promise a requested quantity of verified companies;
  provider quality and page access remain external dependencies.
- Evidence ranking is still routed through qualification in some instructions;
  a dedicated ranking job and artifact are follow-up work.
- Business review, startup advice, and launch planning require declared
  advisory/report artifacts and producer jobs; they are not proven by these
  RevOps runs.
- Runtime evidence is available through the tenant-scoped endpoint, but a
  complete per-mission exported GRAFT bundle is still a tooling follow-up.
- Send authority was not exercised in this pass; side-effecting paths remained
  behind human review.

## Release posture

CRM read/research/draft execution is proven for the exercised contracts. Public
search and advisory claims remain explicitly bounded. The next workstream can
move to the web surface without treating the unproven boundaries as complete.
