# Back To Most Valuable Task (MVT)

## Authoritative playbook

Use `services/assistance/docs/ACTION.md` as the **authoritative** operator playbook.

## Quick reference (keep short)

- **WIP limit = 1**: only one in-progress task at a time.
- **No side quests until SNA is done**.
- **Prefer binary checks**: every SNA should yield pass/fail.
- **Always stop watchers after the SNA** (unless explicitly continuing).
- **After each run**: append a row to the run log below.

## Run log (append/update every run)
Update this after each Back-to-MVT run.

| Date/Time | MVT | SNA | Outcome | What improved (1 sentence) |
|---|---|---|---|---|
| 2026-03-17 17:17 | Make auth screen container status UX foldable, include overall health, and prevent layout overflow | Implement collapsible container status section + overall icon + scrollable auth card; verify build | success | Reduced visual clutter while keeping diagnostics accessible without pushing primary CTA off-screen. |
| 2026-03-17 20:26 | Make Google Sheets memory timestamps typed as Date/Time and make GitHub Actions announcements short on start/completed | Commit+push backend changes for Sheets datetime format + CI started/completed messages; redeploy and verify in UI | pending | Improved operator readability by making timestamps parse as Date/Time and making CI notifications concise. |
| 2026-03-17 20:25 | Add a reliable GitHub Actions watcher loop (start/stop default stop) and persist last run result into memory | Start watcher -> confirm watch/list -> fetch latest run summary -> stop watcher -> write memory `runtime.github_actions.watch.latest` | success | Created a repeatable, bounded deploy-verification loop with a durable memory breadcrumb for the last run result. |
| 2026-03-17 21:30 | Ensure memo routing works (Thai trigger + correct memo sheet config key) | Commit+push backend changes for memo.spreadsheet_name lookup + Thai เมมโม trigger; redeploy and verify memo routes to sheet | success | Memo commands are less fragile: Thai spelling now routes correctly and spreadsheet config supports memo.spreadsheet_name with safe fallback. |
| 2026-03-18 12:45 | Stabilize Sheets logs mirroring so `/jarvis/logs/sheets/status` shows `enabled=true`, non-empty `sheet_name` (env-only), and UI log appends mirror into the `logs` tab | Redeploy backend with env-only sheet_name + enqueue guard; then POST a UI test log and confirm it appears in Sheets | success | Reduced deploy-loop friction by making sheet_name env defaults explicit and verifying end-to-end mirroring from UI append to Sheets. |
| 2026-03-19 09:30 | Capture module ideas/concepts for recent Jarvis refactors into a single doc for future refactors and debugging | Update /back-to-mvt workflow with a module-concepts step + write `services/assistance/docs/JARVIS_MODULES.md` | success | Reduced refactor friction by keeping module purpose, injection points, invariants, and smoke tests in one place. |
| 2026-03-19 12:19 | Validate the deployed GitHub Actions watcher end-to-end (start, observe, auto-stop, persist latest result) | Start watcher (deployed) -> confirm watch/list -> confirm auto-stop reason=completed -> confirm /github/actions/watch returns completed | success | Reduced verification friction by making watch/start failures return structured error detail and fixing ACTION.md watcher endpoints to match runtime. |


