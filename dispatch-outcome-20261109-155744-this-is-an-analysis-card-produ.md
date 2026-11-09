# dispatch-outcome — dispatch-triage-corpus-inventory

**Card:** dispatch-triage-corpus-inventory (analysis card — decision doc, no training)
**Runner:** idc02 · **Date:** 2026-11-09

## What was produced

`docs/ssot/jobs/nest/2026-11-09-dispatch-triage-corpus.yml` — corpus
inventory + labeling-strategy decision doc for the dispatch-triage
suite (ada-voice `tests/bench/suites.yml`, domains.yml kind `triage`,
labels {code, docs, ops, research, clarify}).

## Measured findings (real counts, not estimates)

- **mddb `cascade-outcomes`: 0 rows** — queried all four banks
  (100.102.134.91 :11023/:11026/:11027/:11028); collection unconfigured,
  absent from vector-stats. The designed P5 outcome log was never
  populated (no `scripts/bench-cascade.py` exists).
- **Kanban card corpus:** 1411 files (live+archive), 1127 with action,
  675 `action.type: dispatch`; lane stamped on 82 (post-2026-10-25
  wiring, JEV_LANE-gated); executor 37; model 49; repo 361;
  verified 374 true / 34 false; retry-evidence union (attempts>0 or
  last_failure) 66; 'dispatched' comms events 200 across 166 cards.
  Lane×outcome cross-tab recorded in the doc.
- **On-disk outcome log (this host):** 739 task dirs in
  `~/.local/share/devin-dispatch/tasks/` = 490 plain devin-dispatch
  (no lane/verdict) + 249 opencode-lane attempts WITH
  {card, executor, model, profile, lane, verdict, artifact_landed} —
  verifier-graded labels but pilot-skewed (33 distinct cards;
  video-render-dispatcher family = 72% of rows; verdicts fail 199 /
  pass 17 / skip 4). Other runners hold uncounted slices.
- **Suite state:** hard tier `orch-triage-cases.jsonl` = 30 rows
  (code 5 / docs 5 / ops 8 / research 7 / clarify 5); golden +
  adversarial tiers are `spec` — empty. Golden is hand-labeled by
  suite definition.
- **Adjacent corpora:** card-judgment v4 = 94 rows (different surface),
  focus-inbox = 929 unlabeled operator asks (best future clarify source).

## Key finding

The suite labels **work-type** ({code,docs,ops,research,clarify}) while
dispatch history labels **executor lane** ({free_lane, paid_frontier,
codemod, devin, manual, jules}) — two different taxonomies; the doc maps
each source to the surface it can actually label.

## Decision proposed (board request posted)

★ **(b) arbiter adjudication** — L2/L3 (flash-lite free lane) labels
~700-1400 card texts + confidence; low-confidence to human; the ~100-row
spot-check doubles as the hand-labeled golden seed (subsumes option c).
(a) is cheap but noisy and labels the wrong surface; (c) alone leaves
the hard tier empty. Request id `labeling-strategy-for-the-dispatch-triag-e44673`
raised on the card for Tony to pick a/b/c.

## Verify

- `python3 -c "import yaml; yaml.safe_load(open('docs/ssot/jobs/nest/2026-11-09-dispatch-triage-corpus.yml'))"` — parses clean.
- `curl ... /request` returned `{"ok": true, ...}` HTTP 200.
- Reproduce counts: `/v1/search` on the four banks; yaml-scan of
  `docs/ssot/kanban/cards/**/*.yml`; `ls ~/.local/share/devin-dispatch/tasks | wc -l`.

## Notes / lessons

- board-api write path (`/comment`, `/request`) was intermittently slow
  (POST needed ~2 min; occasional 502 on `/cards`) — use `-m 150`+ on
  board writes; GETs are fast.
- `cascade-outcomes` instrumentation is the real upstream fix: the
  flywheel schema exists in task dirs (meta+usage+verdict) but nothing
  ships it to mddb.

lessons:
  - board-api POSTs to /comment and /request can hang >90s behind a
    serialized writer — always curl with -m 150 minimum on board writes.
  - `verified` on cards is the merge gate, not a routing-quality label —
    free_lane done-cards show verified=False when they produced no commit.
  - The dispatch-triage suite's label surface (work-type) is NOT the
    executor-lane surface classify_lane owns — corpus mapping must pick
    the surface first.
