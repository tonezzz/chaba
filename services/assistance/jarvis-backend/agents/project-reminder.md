---
id: project-reminder
name: Project Reminder
kind: sub_agent
version: 1
---

## Purpose
Capture and manage reminders derived from project/task context.

## Status Payload Contract
- `summary`: short text summary
- `items`: list of upcoming or overdue reminders/tasks
- `blockers`: list of blockers
- `updated_at`: unix timestamp (seconds)
