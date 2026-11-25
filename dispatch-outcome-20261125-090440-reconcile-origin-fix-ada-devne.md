# Dispatch outcome — reconcile origin/fix/ada-devnest-tab-render with master

Card: `land-stranded-fix-ada-devnest-tab-render-05b20f`
Branch: `dispatch/20261125-090440-reconcile-origin-fix-ada-devne`
Commit: `0bc5ea2657` — `fix(ha): render DevNest report and audit missed jobs`

## What was done

Cherry-picked `dd8a1684d2` (the wanted file set from
`origin/fix/ada-devnest-tab-render`) onto current master instead of merging
the stale branch (~530 commits behind, mixed with board-api noise and
cline-tab work already landed separately).

- 11 files landed: `docs/kb/missed-job-sweep.md`,
  `docs/kb/frustration-procedure.md` (+8), `docs/ssot/apps/ssot.apps.node-red.yml`,
  `docs/ssot/infrastructure/ssot.home-assistant.dashboards.yml`,
  `docs/ssot/jobs/board/2026-10-29-missed-job-sweep.yml`,
  `docs/ssot/jobs/devnest/2026-10-28-node-red-devnest-map.yml`,
  `docs/ssot/jobs/home-assistant/2026-10-29-ada-devnest-tab-visual-fix.yml`,
  `docs/ssot/ssot.procedures.yml` (+missed-job-sweep entry),
  `docs/ssot/ssot.repeat-asks.yml`,
  `scripts/home-assistant/mutate-ada-ha-devnest-tab.py`,
  `tests/test_ada_ha_devnest_dashboard.py`.

## Conflict resolution

- `docs/ssot/infrastructure/ssot.home-assistant.instances.yml` — kept HEAD's
  newer text (canonical view order delegated to
  `ssot.home-assistant.dashboards.yml` `chaba_admin_ada`, live order updated
  2026-11-20). The branch's inline view list was stale (missing Kanban 2,
  Diagram, OpenChamber, Ada Code, Node-RED, Wiki, Private Wiki, Hosts,
  Services, Gantt). The DevNest embed description dd8 added is preserved in
  `ssot.home-assistant.dashboards.yml` via the same cherry-pick.
- `docs/home-assistant/dashboards/ada-ha-chaba-admin-current.json` — the
  hunk was a no-op: master's sanitized snapshot (regenerated 2026-11-24)
  already contains the `devnest` view with the CMS embed URL.

## Verification

- `python3 scripts/ssot-prose-smell.py` → 0 flagged values, exit 0.
- `python3 tests/test_ada_ha_devnest_dashboard.py` → 3 tests, all OK
  (pytest not installed; file is unittest-based and runs standalone).
- `docs/kb/missed-job-sweep.md` and the `missed-job-sweep` procedures entry
  (`ssot.procedures.yml:81`) are committed on this branch and will be
  reachable from master on merge — making the filed lesson
  `lesson-4dd48148b1be` (missed-job-sweep-and-safe-opencode-ha-tabs)
  pointers valid.
- `origin/master` advanced 7 commits during the session (all board-api
  comment/action noise); none touch the landed files — clean merge expected.

## Notes

- Working tree has one unrelated unstaged modification:
  `docs/ssot/ssot.dev-system.assessment.yml` (auto-regenerated assessment
  timestamps/scores, not from this task — left uncommitted).
- Not pushed, per dispatch rules.

lessons:
- Cherry-pick `--no-commit` + conflict leaves no CHERRY_PICK_HEAD in this
  git version; just `git commit` the staged result with the original message.
- When a conflicted SSOT note was later refactored to delegate to another
  file, resolve by keeping the delegation and confirming the cherry-picked
  content landed in the delegate — don't re-inline stale lists.
- Regenerated dashboard snapshots can already contain the fix; check the
  live file before assuming a JSON hunk is still needed.
