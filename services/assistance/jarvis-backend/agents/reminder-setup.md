---
id: reminder-setup
name: Reminder Setup
kind: sub_agent
version: 1
trigger_phrases: reminder setup
---

## Purpose
When the user mentions "reminder setup", create a reminder memory item and a local scheduled reminder.

## Behavior
- Extract reminder time from the message (e.g. today/tomorrow + time).
- Write-through to Weaviate authoritative memory.
- Ensure a local reminder is created and scheduled.

## Status Payload Contract
- `summary`: short text
- `reminder_id`: local reminder id (if created)
- `weaviate`: weaviate upsert result (if available)
- `updated_at`: unix timestamp (seconds)
