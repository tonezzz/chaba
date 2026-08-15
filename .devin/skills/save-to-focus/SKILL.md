---
description: Save a task or request from a side session to the focus inbox for later processing
---

# Save to Focus

Use this skill when the user wants to park a task or new request in the focus-inbox without starting work on it. It is the safe way for side sessions to add focus items without editing the active focus files.

## When to use

- The user is in a side session and wants to save a focus item for the active session to process later.
- The user says "save to focus", "add to focus inbox", or references `/save_to_focus`.
- The user gives a title and description (or is willing to provide them) for a new focus item.

## Steps

1. Ask the user for the focus `title` and `text` if they were not provided.
2. Ask for `branch` (optional) and `priority` (optional, default medium).
3. Generate a safe filename from the title and the current UTC timestamp, e.g. `2026-08-15-123456-short-title.yml`.
4. Write a new file in `docs/ssot/focus-inbox/` using the structure from `docs/ssot/focus-inbox/TEMPLATE.yml`.
5. Do not edit `docs/ssot/ssot.focus.current.yml` or `docs/ssot/ssot.focus.yml`.
6. Validate the new YAML file with a quick Python `yaml.safe_load` check.
7. Report the saved file path to the user.

## Examples

### Side session: "save to focus: tony-dell mcp-health optimization"

1. Ask for the description if missing.
2. Set `branch: tony-dell` and `priority: medium`.
3. Write `docs/ssot/focus-inbox/2026-08-15-123456-tony-dell-mcp-health-optimization.yml`.
4. Validate.
5. Report: "Saved to `docs/ssot/focus-inbox/2026-08-15-123456-tony-dell-mcp-health-optimization.yml`. It will be triaged from the active session."

## Notes

- The active session will list `docs/ssot/focus-inbox/*.yml` at startup and ask which item to merge into `ssot.focus.current.yml`.
- This skill does not commit or push. The active session handles the inbox merge and commit.
- If the user only has a vague idea, write a short draft and let the active session refine it during triage.
