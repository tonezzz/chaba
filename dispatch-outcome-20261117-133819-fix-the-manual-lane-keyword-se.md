# Outcome — dispatch-lane-classifier-spend-false-manual (20261117-133819)

## What was wrong

`dispatch_repos.classify_lane` matched `LANE_KW["manual"]` against
title+spec, and bare `"spend"` fired on context-free spec text. On
2026-11-17 three dispatchable cards were forced onto the manual lane:

- `idc03-structural-capacity-15gb-4core-per-2d787f` — spec lists a priced
  option ("costs money — Tony decision") and explicitly asks the agent to
  "implement the non-spend option(s)" — the substring matched anyway.
- `idc03-gemini-ollama-proxy-paid-fallback-2fa021` — spec calls the bug
  "uncontrolled spend".
- `cline-card-review-lane` — spec says "zero paid/model-key spend".

Worse, the stamp was sticky: `_apply_classify_at_queue` skips
classification whenever `action.lane` is set, so a kw-manual stamp
persisted forever (`mddb-embed-free-first` was manually re-pinned
manual→devin on 2026-11-12 and got re-stuck later by the same bug).

## What changed (all three options implemented)

- **(a) sharper spend keywords** — `dispatch_repos.LANE_KW["manual"]`:
  bare `"spend"` replaced with `"spend money"`, `"paid compute"`,
  `"real spend"`, `"costs money"`.
- **(b) title-only manual matching** — manual keywords now match
  `card.title` only. A spend/hardware phrase in the title is the author
  flagging Tony's-hands work; the same words in a spec body are decision
  context. Other lanes still read title+spec.
- **(c) explicit-lane win + audit** —
  `classify_lane` itself now returns an author-declared `action.lane`
  (absence of `lane_source` = author-set) as `(lane, "explicit", 1.0)`;
  board-api stamps `action.lane_source` (`kw`|`jevos`|`fallback`) on
  every classification, and a stamped lane is re-classified on each
  queue so classifier fixes self-heal instead of leaving cards stranded.
  kw-manual audit comms now name the matched keyword
  ("classified as manual (kw:hardware conf 1.00)") and set
  `awaiting_action` so false positives surface for triage. Caller lane
  writes through the re-spawn door drop `lane_source` (explicit wins).
- Vendored copy in `scripts/board/runner-agent.py` updated in lockstep
  (remote runners execute installed copies — they still need the redeploy
  the defer comms already request; queue-time board-api classification is
  the primary gate and is fixed).
- `action.lane_source` documented in `ssot.kanban.yml`.
- Card repair: `idc03-structural-capacity` and `mddb-embed-free-first`
  stamped `lane_source: kw` + audit comm so the next queue re-classifies.
- Deliberately NOT done: the regex-shaped manual kws
  (`restore.*macbook` etc.) were activated — they've been dead
  substrings since 2026-10-25, and activating them would newly
  false-positive `tony-macbook-restore-enroll` (dispatchable SSH/rsync
  work). Left as-is.

## Validation

- **Corpus sweep** — `evals/results/jev/lane-corpus-regression-20261117.json`:
  old-vs-new classification over all 909 kanban cards → **0 regressions
  to manual**, 42 cards unstuck from kw-manual (all spend/buy spec-body
  mentions), 44 other flips are ALL author-declared lanes now winning via
  the explicit path (intended). (The original jev-lane-corpus.json from
  the 23/23 validation was never committed; this artifact regenerates
  the comparison.)
- **Done criterion** — re-classified both 2026-11-17 FP cards:
  `idc03-structural-capacity` → `codemod` (kw:cap),
  `idc03-gemini-ollama-proxy` → `devin` (explicit pin). Both dispatchable.
- **Tests** — `tests/board/test_queue_time_classify.py` +8 cases
  (spec-body spend, title spend-phrase, explicit win, stamped-lane
  re-classify, audit kw in comm). Full `tests/board` suite: 612 tests
  run, only failure is a pre-existing missing-`pytest` import in
  `test_ada_job_envelope` (unrelated environment issue).
- Six cards remain kw-manual — all title hits on `camera`/`rotation`
  that were manual under old rules too (pre-existing title noise, noted
  as follow-up in the job trail).

## Files

- `scripts/board/dispatch_repos.py`, `scripts/board/board-api.py`,
  `scripts/board/runner-agent.py` — classifier + queue-time logic.
- `tests/board/test_queue_time_classify.py` — regression tests.
- `docs/ssot/kanban/ssot.kanban.yml` — `lane_source` documented.
- `docs/ssot/jobs/kanban/2026-11-17-manual-lane-spend-false-positives.yml`
  — decision trail incl. follow-ups (runner-agent redeploy, shadow_eval
  MANUAL_KW, camera/rotation title noise).
- `docs/ssot/kanban/cards/{idc03-structural-capacity-…,mddb-embed-free-first}.yml`
  — provenance repair.
- `evals/results/jev/lane-corpus-regression-20261117.json` — sweep evidence.

## How to verify

```bash
python3 - <<'EOF'
import importlib.util, yaml, urllib.request
urllib.request.urlopen = lambda *a,**k: (_ for _ in ()).throw(Exception("x"))
spec = importlib.util.spec_from_file_location("dr","scripts/board/dispatch_repos.py")
dr = importlib.util.module_from_spec(spec); spec.loader.exec_module(dr)
for cid in ["idc03-structural-capacity-15gb-4core-per-2d787f",
            "idc03-gemini-ollama-proxy-paid-fallback-2fa021"]:
    c = yaml.safe_load(open(f"docs/ssot/kanban/cards/{cid}.yml"))
    print(cid, "->", dr.classify_lane(c, with_detail=True))
EOF
# both print a non-manual lane
python3 -m unittest tests.board.test_queue_time_classify   # from repo root w/ tests on path
```

In production: re-queue `idc03-structural-capacity-15gb-4core-per-2d787f`
via board-api — it should classify to a dispatchable lane (stamped
`lane_source`) instead of staying manual.
