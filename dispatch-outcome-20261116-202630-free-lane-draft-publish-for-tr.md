# Dispatch outcome — trade-lesson-workflows-automation (OPS-0106)

**Result: gate green — done.**

## What ran

`python3 scripts/trade-lesson-migrate.py --topic trade-workflows --apply`
from this dispatch worktree on idc02.

- Dry-run plan: 1 topic `trade-workflows` (working), 8 mapped pages, 51KB
  bundle, all present — no MISSING.
- Drafted on the free lane as specced: `opencode run --standalone --model
  litellm/gemini-3.5-flash-lite` (opencode v2.2.5, LITELLM_KEY from
  `~/.config/secrets/litellm-chaba.env`). opencode rc=0, one shot, no retry.
- Published via board-api `/lesson` upsert → `lesson-8460ed30db74`
  "Education:Trade-Workflows" (4182B html).
- Script appended the drift-map entry itself; committed on this dispatch
  branch (f18a3cbf6f). `wiki-lesson-migrate.py` SERIES already contained
  `'trade'` so no second file changed.

## Gate verification

1. exit=0 — yes ("1 published, 0 skipped, 0 failed [drift-map updated]").
2. `/lesson op:list` — shows `lesson-8460ed30db74`, topic `trade-workflows`,
   level working, modified 2026-11-16T13:30:22Z. (Gate text says
   `trade-trade-workflows`; that is the card-name convention — the actual
   lesson topic is `trade-workflows`, matching `trade-getting-started` et al.)
3. `scripts/lesson-drift-map.yml` — new block
   `lesson-8460ed30db74: # trade-workflows (working)` with all 8 pages.

Lesson body sanity-checked
(`~/var/chaba/trade-lesson-migrate/runs/20261116-202955-trade-workflows/lesson.html`):
house-style h2 + trade-map hub link, 5 h3 sections, real commands/paths
from the sources, no invented flags spotted.

## Environment note (affects sibling cards)

The card assumed idc02 has `~/CascadeProjects/trade` — it does, but only as
a runtime dir (config/data/logs, no git, no docs). The real checkout with
`docs/` + `.docs-mcp/documents.json` is on tony-dell. I rsynced `docs/` and
`.docs-mcp/` into `~/CascadeProjects/trade/` on idc02, so the remaining
sibling topics (trade-ui — trade-knowledge/trade-getting-started already
have live lessons) can now run on idc02 with the script's defaults.

## Verify

- `curl -s -X POST <board-api>/lesson -d '{"op":"list"}'` → topic
  `trade-workflows` present.
- `tail -15 scripts/lesson-drift-map.yml` → `lesson-8460ed30db74` block.
- Wiki: https://wiki.h3.gizmo-thailand.com/index.php?title=Education%3ATrade-Workflows
