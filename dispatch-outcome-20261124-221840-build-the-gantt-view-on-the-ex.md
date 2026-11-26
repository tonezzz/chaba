# Dispatch outcome — board-gantt-timeline-view (2026-11-24 22:18)

## What changed

Commit `7c3cd799fa` on `dispatch/20261124-221840-build-the-gantt-view-on-the-ex`
(+ job record `11dd463e0f`), all under `stacks/web/public/apps/board-gantt/`:

The 2026-11-09 pilot (commits cbafdeccfd…2544ccd487) already had the vendored
frappe/gantt, column colors/progress, click popup, and foldable headers — but
grouping was a hardcoded `GROUPS` registry (adobe-stock only) that silently
dropped every other card. This dispatch generalized it to the card spec:

- **Grouping** (`js/config.js`, `js/groups.js`, `js/data.js`): every in-scope
  card is now charted. Group = first segment of the card's `project: <slug>`
  (explicit field or `project:`/`project: <slug>` tag, normalized);
  `parent/child` slugs nest as `└ child` sub-headers. Untagged cards fall back
  to `PROJECT_ALIASES` (keeps the legacy bare `adobe-stock` tag working — 11
  cards), then `unfiled`. Groups sort by most-recent activity, `unfiled` last.
- **Dates** (`js/tasks.js`): end is now true last activity — max(last comms
  at, updated, created); open cards still run to today; start unchanged
  (first comms → claim.since → created).
- **Top bar** (`index.html`, `js/app.js`): project `<select>` filter with
  per-group counts + refresh (force) button; status line shows bars/groups/
  updated stamp.

## Result / verification

- Node smoke test (724 real cards dumped from card YAMLs): 726 task rows;
  synthetic cases assert project-tag grouping, sub-group nesting, unfiled,
  start/end dates, column progress, fold-collapse, popup html/false.
- Headless Chrome (`--dump-dom` + virtual time) against real `cards.json`
  rendered by the same card dicts: **726 `.bar-wrapper` nodes**, per-column
  classes (172 backlog / 1 lab / 13 doing / 20 review / 518 done), status
  `726 bars · 2 groups`, zero JS errors.
- Spot-check: `board-gantt-timeline-view` bar starts 2026-11-09 (first comms),
  backlog p0, runs to today.
- Scope reality: a same-day mass `updated` touch put all 518 done cards inside
  the 30-day window → ~724 bars. frappe-gantt handles it; fold headers keep it
  navigable.
- Trail: `docs/ssot/jobs/board/2026-11-24-board-gantt-generalized.yml`.

## How to verify live

After merge + the normal web-static sync (no backend/deploy step needed —
files under `stacks/web/public/`):

- `https://tony-ha.surf-thailand.com/apps/board-gantt/` (CF Access) — expect
  ~700+ bars, groups `Adobe Stock` + `Unfiled`, filter dropdown populated.
- chaba-admin **Gantt** tab on ada-ha (already iframes
  `/apps/board-gantt/index.html?v=1`).
- Click a bar → popup with title/column/brief/last comm; click a group header
  → folds its rows.

Note: vendor file is `frappe-gantt.es.js` (ES-module build of frappe/gantt
1.2.2, MIT, LICENSE vendored) rather than `.min.js` — the app is `type=module`.

## lessons

- cards.json is gitignored, rendered only on the served checkout — local
  verification needs `render-board2.py` output or a YAML→JSON dump of
  `docs/ssot/kanban/cards/*.yml`, never a repo file.
- Node can't import the app's `.js` as ESM without `package.json`
  `type:module` — copy `js/` to /tmp with one for smoke tests.
- `google-chrome --headless=new --virtual-time-budget=20000 --dump-dom`
  renders the gantt far enough to count `.bar-wrapper` nodes — cheap DOM
  verification with no browser driver.
