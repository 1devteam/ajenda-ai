# Calendar Provider Contract

The Calendar Provider Contract defines the provider boundary for calendar tool actions.

## Scope

This phase adds only the provider boundary.

It does not:

- add Google Calendar credentials
- call external calendar APIs
- change `tool.invoke`
- change `TaskDispatcher`
- change `WorkerRuntimeService`
- wire role orchestration

## Provider operations

A calendar provider must support:

- `read_events(...)`
- `create_event(...)`

Both operations are tenant-scoped and calendar-scoped.

## Current provider

`LocalCalendarProvider` is the current proof provider.

It is deterministic and tenant-scoped, but it is not durable external calendar storage.

## Future provider

A future real provider can implement this same boundary, such as:

- Google Calendar
- Microsoft Outlook Calendar
- CalDAV

The real provider must preserve the existing action contracts:

- `calendar.read`
- `calendar.create_event`
- `CalendarReadInput`
- `CalendarCreateEventInput`
- `ActionResult`
- `EvidenceItem`
- side-effect policy for writes
