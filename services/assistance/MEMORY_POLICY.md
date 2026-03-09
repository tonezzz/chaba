# MEMORY POLICY

- `README.md`
- `CONCEPT.md`
- `TOOLS_POLICY.md`

## Purpose

This document defines how Jarvis stores, retrieves, and operates on user information.

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

## Retention and deletion

- Users can request forgetting data by deleting or updating memory items in Weaviate
- Reminder records should be marked fired/done when delivered
