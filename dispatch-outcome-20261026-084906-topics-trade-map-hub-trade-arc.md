# Dispatch outcome — lesson-drift-check (OPS-0794)

Card: `lesson-drift-check-flag-lessons-whose-so-dd7ed2`

## What was built

A flag-only drift detector for the trade lesson family (posts 2167–2171:
trade-map hub + trade-architecture, trade-data-sources,
trade-signals-backtest, trade-gold-thb).

- `scripts/lesson-drift-check.py` (new) — reads
  `~/CascadeProjects/trade/.docs-mcp/documents.json` (the same
  `lastModified` the docs-trade MCP serves via `get_page`), cross-checks
  real file mtimes under `docs/` so un-re-indexed edits still count, and
  compares each covered page against its WP lesson's `modified` fetched
  via board-api `/lesson op:list` (no WP creds on the job host). A page
  newer than lesson + 8h grace = stale. A `trade-` topic lesson with no
  map entry flags the hub's inventory. When the stale-set fingerprint
  changes, it files ONE focus-inbox entry via board-api `/inbox`
  (deduped via `~/var/chaba/jobs/lesson-drift-check.json` — daily runs
  don't spam). "Hub lesson comms" resolved to focus-inbox: WP lesson
  posts have no comms channel behind the door.
- `scripts/lesson-drift-map.yml` (new) — declared coverage: 5 lesson
  slugs → 21 docs-mcp page paths, plus `family_prefix`/`hub_slug` for the
  unmapped-topic check.
- `docs/ssot/infrastructure/ssot.jobs.yml` — new `lesson-drift-check`
  entry: `dispatch: dispatcher`, `every: 1d`, `timeout: 90s`,
  `host: tony_dell` (trade docs + index live there), exec checkout
  `~/CascadeProjects/chaba`.
- `docs/ssot/jobs/education/2026-10-26-lesson-drift-check.yml` (new) —
  runbook: mechanism, coverage, decision record, maintenance (add a
  lesson → add a map block), verify commands.

## Decision

Spec's flag-only vs auto-regenerate → **flag-only**, per the spec's own
recommendation: auto-regen writes worse prose than a session that
actually re-learned the material. The inbox entry names the stale pages;
re-learning re-files via `/lesson` (same-slug upsert).

## Verification

- `job-dispatcher.py --host tony_dell --dry-run` shows
  `due lesson-drift-check (every 86400s)`.
- Live run: 5/5 lessons resolved, 21/21 mapped pages present, 0 stale
  (docs last touched Aug; lessons filed Oct-24), 0 unmapped topics;
  state file written.
- `--grace-hours -2000` dry-run forced all 5 stale → detection + report
  format verified.
- All three YAML files `yaml.safe_load` clean; script `py_compile`s.

## Notes for landing

- On tony-dell the job self-activates once this branch merges and the
  exec checkout (`~/CascadeProjects/chaba`) syncs — dispatcher jobs need
  no unit render; `chaba-jobs.timer` picks it up on the next tick.
- Board-api `/lesson` list returns WP-naive `modified`; the 8h grace
  absorbs site-tz-vs-UTC slop on a daily-cadence check.
