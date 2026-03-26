# Assistance Service — Action Reference

Operational quick-reference for the `jarvis-backend` / assistance stack.

---

## Runbooks

| Topic | Document |
|-------|----------|
| Google tools gate — enable/disable | [google-tools-gate-runbook.md](google-tools-gate-runbook.md) |

---

## Google tools gate

Google MCP tools (`google_sheets_*`, `google_calendar_*`, `google_tasks_*`,
`gmail_*`) are controlled by `sys_kv` feature flags.  By default all gates
are **closed** (tools return `HTTP 403`).

See **[google-tools-gate-runbook.md](google-tools-gate-runbook.md)** for:

- Gate keys reference (`google.tools.enabled`, `google.sheets.enabled`, etc.)
- Step-by-step enable / disable checklists
- Verification commands and expected `403` error shape
- Partial enablement examples
- Blast radius and safety notes
