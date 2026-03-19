# Assistance TODO (ideas, next steps, suggestions)

## Now

- [x] TODO-NOW-001: Validate deployed GitHub Actions watcher end-to-end
- [x] TODO-NOW-002: Record deploy snapshot into Memory (`runtime.deploy.snapshot.latest`)
- [x] TODO-NEXT-001: Add a small smoke checklist for operators (calendar reminder + legacy scheduler disabled)

## Next

## Later

- [ ] TODO-LATER-001: Remove legacy reminders system completely (once Calendar cutover is stable)

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

## Tasks + Calendar (workflows)

- Decision: balance Tasks + Calendar
  - Tasks are the backlog/source of truth
  - Calendar is the confirmed execution plan (time blocks)
  - Assistant should suggest blocks, then ask for confirmation before writing
- Decision: organization is project-first
  - Prefer event/task naming by project (e.g. `Alpha: Weekly report (W11)`)
- Decision: follow-up triggers should consider both Calendar + Gmail
  - Calendar meetings can prompt follow-up checklists
  - Gmail threads/labels can prompt follow-up tasks

## Tasks: sequential work (checklists) + template learning

- Decision: represent sequential work as a single task with a checklist (v0)
  - Prefer checklist-in-notes text as canonical for automation/tests
  - Later: optionally mirror into Google Tasks subtasks for UI
- Decision: semi-automatic template learning from completions (suggest + confirm)
  - Infer a template when the same normalized checklist repeats across completed tasks
  - Never auto-apply without confirmation

## Minimal automated tests (start here)

- Checklist parsing + normalization
  - Accept common syntaxes (e.g. `- [ ] step`, `[] step`, `[x] step`)
  - Normalize step text (trim, collapse whitespace)
- Next actionable step selection
  - Choose first incomplete step
  - Return none when all complete
- Template inference (strict v0)
  - Propose template when the exact normalized sequence repeats >= 3 times
  - Otherwise no template

## Fresh start checklist (safe to continue in a new chat)

- Confirm target test framework (recommended: `pytest`)
- Implement pure unit tests for checklist + template inference (no Google API calls)
- Decide where checklist lives (recommended for v0: task notes)
- Only after tests are stable, wire in Google Tasks + Calendar APIs