# Internal Ability Catalog

The internal ability catalog maps every currently registered local/runtime tool action to an `AbilityManifest`.

This catalog is descriptive and non-executing. It does not register handlers, invoke tools, bypass `TaskDispatcher`, bypass `WorkerRuntimeService`, or add external providers.

## Cataloged actions

| Action | Provider | Input schema | Side effect | Resolver |
|---|---|---|---|---|
| `calendar.create_event` | `local_calendar` | `CalendarCreateEventInput` | `internal_write` | none |
| `calendar.read` | `local_calendar` | `CalendarReadInput` | `none` | none |
| `http.request` | `httpx` | `HttpRequestInput` | `external_read` | `http_request_side_effect` |
| `record.read` | `local_records` | `RecordReadInput` | `none` | none |
| `record.search` | `local_records` | `RecordSearchInput` | `none` | none |
| `record.write` | `local_records` | `RecordWriteInput` | `internal_write` | none |
| `sales.create_followup_task` | `local_sales` | `RecordWriteInput` | `internal_write` | none |
| `sales.draft_followup` | `local_sales` | `FollowupDraftInput` | `none` | none |
| `sales.log_activity` | `local_sales` | `RecordWriteInput` | `internal_write` | none |
| `sales.qualify` | `local_sales` | `SalesLeadInput` | `none` | none |
| `sales.recommend_next_action` | `local_sales` | `SalesLeadInput` | `none` | none |
| `sales.research` | `local_sales` | `SalesLeadInput` | `none` | none |
| `sales.score_lead` | `local_sales` | `SalesLeadInput` | `none` | none |
| `webhook.dispatch` | `WebhookDispatchService` | `WebhookDispatchInput` | `external_send` | none |

## Policy notes

- All manifests require evidence.
- Internal writes require approval and readback.
- `http.request` is declared as `external_read` with a maximum side-effect class of `external_write` because write methods resolve dynamically.
- `http.request` requires approval and idempotency because its resolver can produce external writes.
- `webhook.dispatch` requires approval and idempotency because it sends to external webhook endpoints.
- External-state readback for HTTP and recipient-side webhook verification is deferred to provider-specific adapters.
- No real external providers are added by this catalog.
- No role orchestration is added by this catalog.

## Next phase

After this catalog is merged, the next promotion-gate step can add a validation script that fails when the default action registry and internal ability catalog drift.
