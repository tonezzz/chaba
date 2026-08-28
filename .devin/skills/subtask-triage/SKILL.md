# Subtask Inbox Triage

## What it does

At the start of each session, after reading `docs/ssot/ssot.focus.current.yml`, this skill evaluates the active focus subtasks and decides whether any of them are concrete enough to become a `docs/ssot/focus-inbox/` draft. This keeps subtasks from clogging the active focus while avoiding multi-file churn.

## When to invoke

Invoke this skill at session start, immediately after the `ssot.focus.current.yml` read, and whenever the user asks "what should I do next with these subtasks?".

## Trigger

- The active shared or branch focus has `subtasks`.
- The assistant has just read `docs/ssot/ssot.focus.current.yml`.

## Inputs

- `active_focus_label`: the label of the active focus
- `subtasks`: the list of active subtasks from `ssot.focus.current.yml`
- `quick_win_criteria`: the criteria from `ssot.focus.current.yml`

## Rules

1. **Read-only inputs** — only read `docs/ssot/ssot.focus.current.yml` and the quick-win criteria.
2. **One-file writes only** — if a subtask graduates to inbox, create exactly one `docs/ssot/focus-inbox/YYYY-MM-DD-<slug>.yml` file. Do not modify `ssot.focus.current.yml`, `ssot.focus.yml`, or any active focus.
3. **Inbox-ready criteria** (all must be true):
   - Concrete and self-contained: one deliverable, one file, one command, or one small verification.
   - Fits the quick_win_criteria in `ssot.focus.current.yml`.
   - Not blocked by the current active focus or a missing dependency.
   - Can be completed without user approval, new dependencies, multi-host deploys, or destructive operations.
4. **If not inbox-ready**, return a one-sentence reason and leave the focus unchanged.
5. **Park, do not delete** — never remove a subtask from the active focus; only create an inbox draft for it.

## Output

Return a JSON object:

```json
{
  "action": "drafted" | "kept",
  "subtask": "<label>",
  "reason": "one-sentence explanation",
  "draft_path": "docs/ssot/focus-inbox/YYYY-MM-DD-<slug>.yml" | null
}
```

## Related documentation

- `docs/ssot/ssot.focus.current.yml`
- `docs/ssot/infrastructure/ssot.focus.triage.yml`
- `docs/ssot/infrastructure/ssot.focus-dispatcher.yml`
