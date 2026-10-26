# board-project-rollup — per-project rollup band + board-api query params

Built the missing project view end-to-end:

- **`scripts/lib/projects.py` (new)** — shared helpers:
  `card_projects()` unions the `project: <slug>` tag (space-tolerant,
  case-normalized) with a dedicated `project:` field (str|list);
  `project_rollup()` emits per-project slug, member count, `by_column`
  tallies, stage, open ask/request count, a `next_action` line
  (open ask > running/queued > doing > top-priority card), and the
  member card list (id/title/column/priority/needs_you).
- **`scripts/render-board.py` + `scripts/render-board2.py`** — both
  payloads now carry `projects`; both pages render a collapsible
  "📁 Projects" band: stage chip, per-column count chips, member rows
  (click → card modal), next-action line, and a CMS-page link
  (`/cms/#/<slug>` — page slug = tag value per the lifecycle SOP).
  Clicking a project slug filters the board to `project:<slug>` (click
  again to clear). Both views' filter haystacks now include
  tags + project with `x: y` → `x:y` normalization — `project:slug`
  queries match either tag spelling. board2 is the live default view;
  the classic page keeps feature parity for the revert path.
- **`scripts/board/board-api.py`** — `GET /cards?project=<slug>`
  returns that project's rollup + member cards (`&cards=0` omits them;
  unknown slug → 404 + `known` list); `GET /cards?projects` returns all
  rollups. Stage is read from the linked ada-cms-pages doc via MDDB
  (`meta.stage` or a `stage:` body line, 4s timeout, list view bounded
  to 8 slugs) with a column-derived fallback — a dead MDDB degrades the
  stage, never errors the endpoint. `POST /card` accepts `project`
  (str|list, stored lowercased). Also added repo `scripts/` to
  sys.path, which repairs the previously-silent `from lib.cms_index`
  ImportError in the /report create path.
- **`docs/ssot/kanban/ssot.kanban.yml`** — card_schema documents
  `tags`/`project`; write_path documents the new query params.
- **`docs/ssot/jobs/kanban/2026-10-26-board-project-rollup.yml`** —
  job trail.

## Verify

- `python3 -m unittest tests.board.test_project_rollup` — 19 tests, OK
- `python3 scripts/board/board-api.py --selftest` — OK (new coverage:
  project field passthrough, view codes, CMS-degrade)
- `python3 -m unittest discover -s tests/board` — 224 tests, OK
- Live HTTP smoke on a test port with an injected payload:
  `?projects` → correct rollup (`stage: "in flight"`, `next_action` =
  the open ask); `?project=demo-app` → rollup + 2 member cards;
  `?project=nope` → 404 `{"known": ["demo-app"]}`
- `node --check` on both pages' script bodies — valid
- Rendered board on this worktree: `projects: []` in cards.json —
  correct, no cards carry the tag yet; the band self-hides until the
  first `project:` card exists.

## Deploy note

cards.json/index.html are gitignored — the serving host's
chaba-board-render.timer (60s) picks the renderers up on merge;
board-api.service needs a restart for the new GET handler + /card
field. No cards need retrofitting — the `project:` tag starts working
the moment Ada/the intake router files the first tagged card.
