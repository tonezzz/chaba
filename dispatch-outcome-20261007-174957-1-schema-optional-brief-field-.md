# Dispatch outcome — kanban-card-brief

Card: `kanban-card-brief` — optional `brief` field on cards: plain-language
situation + expected action, rendered prominent on board2, backfilled on
active cards, convention documented.

## What changed

- **`docs/ssot/kanban/ssot.kanban.yml`** — `brief` documented in
  `card_schema`: 2-3 sentences max, plain language for the operator,
  situation first then expected action, no jargon/IDs. Convention stated:
  every new card gets a brief; whoever writes the card writes it.
- **`scripts/render-board2.py`** — card detail shows `brief` as a
  prominent sky-bordered "In plain terms" callout above note/spec;
  card-list rows show the first line as a truncated subtitle with the
  full brief on hover (title attr, quote-escaped); the filter search
  includes brief text. `brief` flows into cards.json automatically via
  `yaml.safe_load` passthrough — no pipeline change needed.
- **`scripts/board/backfill-briefs.py`** (new) — rerunnable catch-up
  pass. Inserts a one-line `brief:` before `column:` (minimal git diff;
  card files are flock-managed and merge across parallel sessions).
  Situation is derived from the note/title with dateline stripping;
  expected action from column + open requests + blocked_by +
  review_kind. An `OVERRIDES` table holds hand-written briefs for the
  ~30 cards whose own text couldn't produce plain language.
- **43 active (non-done) cards backfilled** — one added line per file,
  all 202 cards still parse as YAML.
- **`scripts/ada/{gev-auto-health,logs-kanban,disk-trend-watch,cms-auto-health}.py`**
  — the four health-lane card generators now emit a `brief` when they
  upsert review cards.
- **`docs/ssot/jobs/kanban/2026-10-07-kanban-card-brief.yml`** — job trail.

## Verification

- `grep -q 'c.brief' scripts/render-board2.py` — pass (expected goal 1)
- `grep -l '^brief:' docs/ssot/kanban/cards/*.yml | wc -l` = 43 > 10
  (expected goal 2)
- `python3 scripts/render-board2.py` — regenerated board2 page +
  cards.json (202 cards); embedded JS passes `node --check`; tooltip
  attribute escaping verified against a quote-containing brief.
- `python3 scripts/board/backfill-briefs.py --dry-run` — idempotent
  (0 would-update after the pass).
- All edited Python compiles; job YAML and ssot.kanban.yml parse.

## Notes for review

- The classic board (`render-board.py`) was intentionally untouched per
  the card spec — brief currently only shows on the tabs view
  (`/apps/board2/`).
- Column `todo` exists on live cards but isn't in the manifest's column
  list — treated as backlog-equivalent in the backfill action text;
  unrelated quirk, not fixed here.
