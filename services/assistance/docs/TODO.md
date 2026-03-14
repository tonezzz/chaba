# Assistance TODO (ideas, next steps, suggestions)

## General

- assess README.md before proceeding with any new features
- Improve this file & other docs accordingly.

## Reminders: Google Calendar cutover follow-ups

- Remove legacy reminders system completely (once Calendar cutover is stable)
  - Delete legacy reminder scheduler loop and related code paths
  - Remove/retire SQLite `reminders` table usage as a notification scheduler
  - Remove or repurpose Weaviate `kind=reminder` storage if Calendar is authoritative going forward
  - Ensure UI/agents/tooling no longer assumes local reminder IDs exist for new reminders

## Reminders: Calendar UX / features

- Add mapping/traceability fields on Calendar events
  - Store stable identifiers in `extendedProperties.private` (e.g. `jarvis_source`, `trace_id`, `jarvis_user_id`)
  - Consider adding a short event prefix or emoji for scanability (if desired)
- Improve reminders_minutes policy
  - Allow multiple overrides (e.g. 10m + 0m)
  - Make default configurable
- Add support for recurring reminders end-to-end
  - Propagate RRULE from user intent through tools and agent flows
  - Decide policy for exceptions / single-instance edits

## MCP / 1MCP operational gotchas (keep in mind)

- 1MCP stdio child servers do not automatically inherit all env
  - Use per-server `env` blocks in `mcp.json` for required vars
- Portainer/docker-compose interpolation gotcha
  - If generating `mcp.json` via heredoc, escape placeholders with `$${VAR}`
  - Otherwise Portainer may expand `${VAR}` at deploy time to empty strings

## Testing / verification

- Add a small smoke checklist for operators
  - Create calendar reminder via `POST /reminders`
  - Confirm event appears in `Jarvis Reminders`
  - Confirm legacy scheduler remains disabled by default
  - Confirm legacy `/reminders/{id}/done` still works for existing local reminders