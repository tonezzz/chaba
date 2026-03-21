# Assistance TODO (ideas, next steps, suggestions)

## Now

- [ ] TODO-NOW-012: Refresh ACTION.md status chart snapshot (run /status, /health, /github/actions/latest)
- [x] TODO-NOW-011: Docs upkeep pass (finalize Now/Next/Later structure; keep one active Now item)
- [x] TODO-NOW-010: TODO.md drift fix (dedupe Now list; tighten ordering; remove obvious duplication)
- [x] TODO-NOW-009: Deploy verification completeness (fill digest/created/published fields reliably; tighten redeploy decision)
- [x] TODO-NOW-008: Status loop polish (make ACTION.md Now loop more mechanical)
- [x] TODO-NOW-007: Docs cleanup pass (tighten ACTION.md ordering; remove drift/duplication)
- [x] TODO-NOW-006: Make `/health` authoritative (non-null `build.git_sha` and `build.image_tag`)
- [x] TODO-NOW-005: Add operator-friendly WS reminders smoke helper and reference it from ACTION.md
- [x] TODO-NOW-004: Sync runbooks + status with deployed behavior (WS reminders) and push ACTION.md change
- [x] TODO-NOW-001: Validate deployed GitHub Actions watcher end-to-end
  - Evidence (2026-03-19):
    - `GET /jarvis/api/github/actions/latest?owner=tonezzz&repo=chaba&branch=idc1-assistance` => run `23291000409` status=`completed` conclusion=`success`
    - `POST /jarvis/api/github/actions/watch/start` => started ok; `GET /jarvis/api/github/actions/watch/list` => `running=false` `stopped_reason=completed` and last `run` persisted
- [x] TODO-NOW-002: Record deploy snapshot into Memory (`runtime.deploy.snapshot.latest`)
- [x] TODO-NEXT-001: Add a small smoke checklist for operators (calendar reminder + legacy scheduler disabled)
  - Added to `services/assistance/docs/ACTION.md` (Operator smoke checklist)
- [x] TODO-NOW-003: Remove legacy reminders system completely (once Calendar cutover is stable)
  - Evidence (2026-03-19): removed legacy SQLite `reminders` table usage, scheduler loop, and legacy WS actions; Calendar-based reminder creation preserved; `python -m py_compile services/assistance/jarvis-backend/main.py` passed

## Next

- Re-enable Google tools gate (when Jarvis is stable)
  - Google MCP tools are currently gated by sys_kv keys: `google.sheets.enabled`, `google.calendar.enabled`, `google.tasks.enabled`, `gmail.enabled`
  - Goal: add a safe rollout checklist + explicit enable/disable procedure

## Later

## General
- assess README.md before proceeding with any new features
- Improve this file & other docs accordingly.

## Reminders: Google Calendar cutover follow-ups

- Canonical procedures + verification live in `services/assistance/docs/ACTION.md`:
  - `Runbooks -> Operator smoke checklist (Calendar cutover)`
  - `Runbooks -> Legacy reminders removal (breaking)`

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
  - See `services/assistance/docs/ACTION.md` -> `Runbooks` -> `Operator smoke checklist (Calendar cutover)`

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