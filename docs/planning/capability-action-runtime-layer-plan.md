# Capability Action Runtime Layer

Status: implemented first additive slice with local proof providers and a narrow durable evidence bridge for completed `tool.invoke` outputs.

## Implemented runtime truth

- `tool.invoke` is a registered `TaskDispatcher` handler, not a new dispatcher or worker loop.
- Actions execute only after an `ExecutionTask` has moved through the existing queue, worker claim/start, lease, and dispatcher path.
- Handler results are returned to the dispatcher and persisted through the existing task-output lineage path when completion succeeds.
- Evidence-shaped `tool.invoke` output is also bridged into tenant-owned `EvidenceRecord` rows from `WorkerRuntimeService.complete` after task-output lineage is appended, keeping evidence persistence behind the existing queue/lease/dispatcher completion authority.
- Capability and adapter records remain declarative metadata; they are resolved through existing repositories for validation and do not register executable actions.

## Implemented actions

- Record actions: `record.search`, `record.read`, `record.write`.
- Sales actions: `sales.research`, `sales.qualify`, `sales.score_lead`, `sales.recommend_next_action`, `sales.draft_followup`, `sales.log_activity`, `sales.create_followup_task`.
- HTTP action: `http.request` with HTTPS-only, internal-hostname/IP/DNS blocking, and write-method side-effect classification.
- Webhook action: `webhook.dispatch`, reusing `WebhookDispatchService`.
- Calendar actions: `calendar.read`, `calendar.create_event` using a tenant-scoped local proof provider.
- Aliases: `crm.research` and `gtm.message_draft`.

## Safety boundaries

- Side-effecting actions fail closed unless a versioned `execution_constraints.side_effect_authorization` envelope authorizes the concrete action and capability/adapter gates pass when references are present.
- Local record and calendar providers are deterministic, tenant-scoped, resettable proof providers. They are not durable CRM or calendar storage.
- `http.request` rejects localhost, `.local`, obvious internal hostnames, unsafe schemes, private/link-local/loopback/multicast/reserved IP literals, and private DNS resolutions where resolution is available.

## Remaining gaps

- Outcome review bridge implemented for high-risk GTM side-effects (auto-draft on WorkerRuntimeService.complete).
- Retrieval bridge advanced (contracts used for source evidence/provenance in hybrid); full engine deferred.
- Live external (CRM with real network_egress in crm.research/crm_upsert/social; email real; calendar/cred) mostly wired; Wasm/TEE sandbox contract layer started for untrusted execution (cutting edge).
- The action registry is in-process and deterministic; it is intentionally separate from the declarative capability and adapter registries.
