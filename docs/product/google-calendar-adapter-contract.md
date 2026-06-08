# Google Calendar Adapter Contract

This contract defines the Google Calendar provider adapter shape before live external API integration.

## Scope

This phase adds a provider adapter shell only.

It does not:

- import the Google SDK
- call Google Calendar APIs
- resolve credentials
- refresh OAuth tokens
- store credentials
- change `tool.invoke`
- change `TaskDispatcher`
- change `WorkerRuntimeService`

## Provider boundary

`GoogleCalendarProvider` implements the existing `CalendarProvider` contract:

- `read_events(...)`
- `create_event(...)`

The provider requires an `ExternalCredentialReference` with:

```text
provider = google_calendar
tenant_id = caller tenant_id
