# MEMORY POLICY

- `README.md`
- `CONCEPT.md`
- `TOOLS_POLICY.md`

## Purpose

This document defines how Jarvis stores, retrieves, and operates on user information.

Ground truth spec:
- `docs/WEAVIATE.md`

## Storage model (Weaviate + local scheduler)

### Authoritative memory

Jarvis stores long-lived information in Weaviate as memory items (e.g. reminders, todos, notes). Items should be written idempotently and be queryable by both structured filters and (optionally) semantic search.

### Operational scheduler cache

Jarvis also stores machine-readable reminder schedule state locally (SQLite) for reliable time-based notification delivery.

## What Jarvis should store

- Stable facts that help future conversations
- User preferences
- Project context and definitions
- Reminders and tasks (see "Reminders")

## What Jarvis must not store

- Secrets (API keys, passwords, private keys)
- Highly sensitive data unless explicitly requested by the user

## Observation content guidelines

- Always store the original user sentence as an observation
- Add normalized observations to reduce ambiguity
- Prefer short, atomic statements

## Entity types

Jarvis should use a consistent taxonomy. Recommended values:

- person
- place
- project
- concept
- preference
- task
- reminder
- note

## Reminders (recall + notifications)

### Dual-write rule

When the user expresses a time-based intention (e.g. "Remember I need to check out tomorrow at 9am"), Jarvis should:

1. Store a human-readable memory item in Weaviate (for recall/search)
2. Store a machine-readable reminder record in the backend reminders table (for notifications)

Write ordering (reliability):
1. Write to local SQLite first (scheduler continuity)
2. Write-through to Weaviate (cross-device consistency)
3. If Weaviate is temporarily unavailable, the local scheduler still runs; resync/retry should reconcile later.

### Time normalization

- Relative time phrases (e.g. "tomorrow 9am") are resolved in the backend
- The system uses the user profile timezone when available
- Default timezone: `Asia/Bangkok`

### Normalized observations

When a due time is detected, Jarvis should add the following observations:

- `TIMEZONE: <tz>`
- `ISO_TIME: <utc timestamp>`
- `LOCAL_TIME: <local timestamp>`

### Notification policy

- Default schedule type: `morning_brief`
- Optional: notify 1 hour earlier (user choice)

### Reminder lifecycle

Jarvis should support a reminder lifecycle that allows reminders to disappear from "today" views when completed:

- `pending`: scheduled and not yet fired
- `fired`: notification was delivered (but not yet acknowledged as done)
- `done`: user marked it complete/done (terminal)
- `cancelled`: user cancelled it (terminal)

Completion mechanism:
- HTTP: `POST /reminders/{reminder_id}/done`
- Tool call: `reminders_done` (`{ "reminder_id": "..." }`)

"Today" reminder views should typically include:
- `pending` reminders due/notify today
- `fired` reminders that are still not `done`

"Done" reminders should not appear in the pending/today list, but may appear in history.

### Dedupe semantics

Jarvis must not over-dedupe reminders just because they share the same time.
For example, "do job1 at 9:00am" and "do job2 at 9:00am" must create two reminders.

Recommended dedupe key shape:
- `dedupe_key = normalize(title) + "|" + due_at_ts + "|" + schedule_type`

This prevents true duplicates (same normalized title + same time + same schedule type), while allowing distinct titles at the same time.

## Retention and deletion

- Users can request forgetting data by deleting or updating memory items in Weaviate
- Reminder records should be marked fired/done when delivered
