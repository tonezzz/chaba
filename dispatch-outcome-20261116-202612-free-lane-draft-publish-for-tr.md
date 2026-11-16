# dispatch outcome — trade-lesson-knowledge-base (OPS-0107): free-lane draft+publish for topic trade-knowledge

## Result: DONE — lesson published, gate met

Ran `python3 scripts/trade-lesson-migrate.py --topic trade-knowledge --apply`
from this worktree on idc02. opencode v2.2.5 + `litellm/gemini-3.5-flash-lite`
(free lane) distilled the 15-page, 72KB doc bundle into a 3608B HTML lesson
body in house format (h2 title, trade-map hub link, 5 h3 sections:
TradeCanvas/hindsight strategies, containerization, ops commands,
best-practices/patterns, troubleshooting).

Published via board-api `/lesson` upsert:
**`lesson-be94e95accf5` — topic `trade-knowledge`, level working**
(Education:Trade-Knowledge; Thai section appended by the door).

## Gate verification

- exit=0: `1 published, 0 skipped, 0 failed [drift-map updated]` ✓
- `/lesson op:list` shows `lesson-be94e95accf5 | trade-knowledge` ✓
  (card gate reads "trade-trade-knowledge" — the documented double-prefix
  typo in the child-card specs; real topics are single-prefix `trade-*`,
  matching the existing family and `family_prefix: trade-` drift check —
  see `docs/ssot/jobs/education/2026-11-13-trade-lesson-migrate.yml`
  `decision.topic_naming`)
- `scripts/lesson-drift-map.yml` gained `lesson-be94e95accf5:
  # trade-knowledge (working)` + all 15 source pages — committed on this
  dispatch branch as `060de9827a` ✓

## Notes for the record

- idc02's `~/CascadeProjects/trade` is a deploy/data dir (config/data/logs)
  with no `docs/` — same finding as the migrate-script dispatch. Source
  docs were rsync'd fresh from `idc03:~/CascadeProjects/trade/{docs,
  .docs-mcp}` into `/tmp/trade-docs-fixture/` (63 md files, 62 indexed
  pages) and passed via `--docs-root`/`--index`.
- Run evidence: `~/var/chaba/trade-lesson-migrate/runs/20261116-202847-trade-knowledge/`
  (bundle.md, prompt.md, events.jsonl, lesson.html, run.log).
- Remaining unpublished topics from OPS-0103's map: trade-ui and
  trade-workflows (their own cards).

## How to verify

```
curl -s -X POST $BOARD_API/lesson -H 'Content-Type: application/json' \
  -d '{"op":"list"}' | grep trade-knowledge
grep -A18 'lesson-be94e95accf5' scripts/lesson-drift-map.yml
```
