# Dispatch outcome: trade-lesson-ui-integration (free-lane draft+publish, topic trade-ui)

## What was done

Ran `python3 scripts/trade-lesson-migrate.py --topic trade-ui --apply`
from the synced chaba exec checkout on **tony-dell**
(`~/CascadeProjects/chaba` @ b30bed39e0 = origin/master). The trade
checkout + opencode + `~/.config/secrets/litellm-chaba.env` all live on
tony-dell; idc02's `~/CascadeProjects/trade` is only a data dir
(config/data/logs) so the run was executed over ssh with
`PATH=$HOME/.local/bin:$PATH` (opencode sits in `~/.local/bin`, not on
the non-login PATH).

- Bundle: 8 pages / 73KB (6 `features/ui/*` pages +
  `core/VISUALIZATION_GUIDE` + `ssot/ui-compare-family-design`, per
  `scripts/trade-lesson-map.yml`).
- Draft: `opencode run --model litellm/gemini-3.5-flash-lite` (free
  lane), rc=0, 6 events → 3811B HTML fragment. Run artifacts:
  `tony-dell:~/var/chaba/trade-lesson-migrate/runs/20261116-203051-trade-ui/`
  (bundle.md, prompt.md, events.jsonl, lesson.html, run.log).
- Publish: board-api `/lesson` upsert → **created
  `lesson-72f75ef5c113` (topic `trade-ui`, level working)**.
- `scripts/lesson-drift-map.yml` on tony-dell gained the
  `lesson-72f75ef5c113` → 8 pages entry; the identical entry is
  committed here on the dispatch branch
  (`a4512a9c87`) so it reaches master at close-out and tony-dell's
  dirty file converges on the next repo-sync.

## Gate check

- exit=0 — yes (`1 published, 0 skipped, 0 failed [drift-map updated]`).
- `/lesson op:list` — shows `trade-ui -> lesson-72f75ef5c113`.
  Note: the card's gate text says `trade-trade-ui`, but that is a
  systematic typo across all four sibling cards (`trade-trade-*`); the
  map and the already-published sibling use bare `trade-*` topics
  (`trade-getting-started` published as `trade-getting-started`).
  Published under `trade-ui` accordingly.
- `scripts/lesson-drift-map.yml` has a `trade-ui` entry — yes
  (`lesson-72f75ef5c113`, comment `# trade-ui (working)`).
- SERIES already contained `"trade": "Trade"` — no wiki-lesson-migrate
  edit needed.

## Sibling status (observed via op:list)

`trade-workflows -> lesson-8460ed30db74` and
`trade-knowledge -> lesson-be94e95accf5` also published today by the
two parallel dispatches; `trade-getting-started` was already up.

## Verify

```
curl -s -X POST https://idc03.taila0626a.ts.net:10000/lesson \
  -d '{"op":"list","from":"devin"}' -H 'Content-Type: application/json' \
  | grep trade-ui          # -> lesson-72f75ef5c113
grep -n trade-ui scripts/lesson-drift-map.yml   # entry + 8 pages
```
