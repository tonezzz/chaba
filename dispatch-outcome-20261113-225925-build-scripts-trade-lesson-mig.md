# dispatch outcome — build scripts/trade-lesson-migrate.py (OPS-0103)

## What changed (committed on dispatch/20261113-225925-build-scripts-trade-lesson-mig, commit 49e66f971d)

- `scripts/trade-lesson-migrate.py` (new, 522 lines) — deterministic
  orchestrator: docs-mcp inventory -> coverage map -> `opencode run`
  free-lane distill -> board-api `/lesson` upsert -> drift-map + wiki
  SERIES update. The LLM only distills prose.
- `scripts/trade-lesson-map.yml` (new) — coverage map for all 62
  docs-mcp pages: 5 existing lessons (17 pages), 4 new topics matching
  the child cards (trade-getting-started 1p, trade-ui 8p,
  trade-workflows 8p, trade-knowledge 15p), 8 pages skip:true
  (docs-governance meta + host/project evals), 0 uncovered. Synthesis
  lessons (trade-gold-thb) use `topics.<name>.extra_pages` since a page
  has one primary owner.
- `scripts/lesson-drift-map.yml` — appended `lesson-0f4811f49a34`
  (trade-getting-started, intro) with its page list, written by the
  script's own --apply path.
- `scripts/wiki-lesson-migrate.py` — `SERIES` gained `"trade": "Trade"`,
  applied by the script on first successful publish.
- `docs/ssot/jobs/education/2026-11-13-trade-lesson-migrate.yml` — job
  trail doc in the established format.

## Design notes

- Flags: `--dry-run` (default, plan only — no LLM, no writes), `--apply`,
  `--topic SUBSTR`, `--model` (default `litellm/gemini-3.5-flash-lite`),
  `--docs-root`, `--index`, `--map`, `--run-dir`, `--state`,
  `--no-hash-skip`, `--all-topics`, `--timeout`, `--sleep`.
- Missing map file seeds from `lesson-drift-map.yml` (topic/level parsed
  from the `# slug # topic (level)` comments) and is persisted on
  --apply; uncovered index pages get a proposed mapping printed in
  --dry-run as a paste-ready YAML block.
- opencode: `opencode run --format json --standalone --model <m>
  -f bundle.md "<prompt>"` (v2 detected via `opencode --version`);
  `LITELLM_KEY` armed from `~/.config/secrets/litellm-chaba.env` for
  litellm/* models. Run evidence (prompt, bundle, events.jsonl,
  lesson.html, run.log) under `~/var/chaba/trade-lesson-migrate/runs/`.
- Publish: `POST /lesson {topic, level, source:"link", content: html}` —
  upsert by topic slug; Thai section appended by the door.
- Idempotent: lesson upsert + content-hash skip in
  `~/var/chaba/trade-lesson-migrate/state.json` + drift-map append
  keyed on slug.

## Verified

- Dry-run over a fresh rsync of the real docs from idc03 (idc02's
  `~/CascadeProjects/trade` has no docs/ — the checkout here is the
  deploy dir only; the docs tree lives on tony-dell + idc03): plan shows
  62 pages, 5 existing lessons skipped, 4 NEW topics to draft.
- Real `--apply --topic trade-getting-started`: opencode produced a
  2370B HTML body in the house format; `/lesson` created
  `lesson-0f4811f49a34` (Education:Trade-Getting-Started, intro,
  next_review +7d); drift-map entry + SERIES edit landed; state hash
  recorded.
- Re-run of the same command: `skip (lesson exists)` — idempotent.
- Seeded-map path exercised via `--map /tmp/nonexistent.yml`: drift-map
  inversion works; 42 uncovered pages got proposed YAML.

## Caveats / follow-ups

- The four child cards gate on topic names `trade-trade-*` — that's a
  double-prefix typo in their specs; the real topics are single-prefix
  (`trade-getting-started` etc.), matching the existing family and the
  `family_prefix: trade-` drift check. Noted on the card.
- Remaining 3 topics (trade-ui, trade-workflows, trade-knowledge) are
  drafted but NOT yet published — they're the child cards' job;
  `--apply --topic <x>` on a host with the docs tree will run them.
- board-api `/comment` and `/card` timed out early in the session while
  `/lesson` stayed fast (transient); progress comment posted fine later.
