# Dispatch outcome — devnest-free-lane-savings-pilot (OPS-0885 execution)

## What happened

Executed Tony's approved answer ("queue all three on tony-dell now — I am
watching"): queued `devnest-fl-pilot-{doc,code,report}` via board-api and
ran the supervised pilot on tony-dell with a manual runner-agent loop
(`JEV_LANE=0 OPENCODE_LANES=1` — dell has no runner-agent.service; only the
drop-in from the OPS-0846 proof exists, so supervised = deliberate manual
runs, same as the proof).

## Pilot results — all three are valid free-lane datapoints

executor `opencode:free_lane`, model `litellm/gemini-3.5-flash-lite`,
0 human-intervention min, 0 escalations on all three.

| job | class | wall | tokens in/out | gate | merge |
|---|---|---|---|---|---|
| doc | docs-config | 36s | 35,070/409 (+100k cache) | pass — 5 headings on master | merged 8ea5303d |
| code | small testable fix | 46s | 80,999/816 (+102k cache) | pass — pytest 3/3 on merged | merged b9ede30a |
| report | read-only report | 38s | 56,656/826 (+196k cache) | pass — 7 lane ids + free_lane | pushed 874a9924, sweep pending |

LiteLLM SpendLogs delta (list-price, not billed): doc+code shared window
$0.0447 (321,831 tok), report $0.0253 (254,675 tok) → **$0.0700 / 3 passed
gates = $0.0233 per gate**. Devin baseline (matched same-day runs): doc
57.9s, code 66.1s — free lane 30–38% faster on wall, identical merge
trajectory. Devin is allowance-priced so per the lane-savings hard rule the
claim is tokens+wall+intervention, not dollars. No paid-frontier arm ran.

Run records: `docs/ssot/jobs/devnest/pilot-runs/2026-10-26-*.yml`
(+ retroactive run0 for `opencode-closeout-probe-dell`).

## Bugs the pilot surfaced — fixed in this dispatch

- **runner-agent `claim_pass` clobbered pinned `action.lane`** under
  `JEV_LANE=1` — the doc card would have re-classified to `codemod` (devin
  executor) and the code card to `paid_frontier` (real spend), repeating
  the OPS-0885 miss class. Fix: explicit lane wins before classifying;
  `model` fills from `LANE_MODELS` only when unset
  (`scripts/board/runner-agent.py`, +3 regression tests).
- **merge-sweep `TASK_ID_RE` couldn't parse OpenCode-lane tids**
  (`devin-task-<card-id>-<epoch>` vs `devin-task-<YYYYMMDD-HHMMSS>-*`), so
  once `finish_pass` consumed runner state.json, a held opencode merge was
  invisible to the sweep — `devnest-fl-pilot-report`'s branch sat
  pushed-but-unmerged past a sweep tick. Fix: regex accepts both shapes
  (+4 regression tests). The report branch lands on the next sweep tick
  after this session's merge reaches the served checkout.

## Known remainders

- `devnest-fl-pilot-report` merge: pending merge-sweep tick post-deploy
  (artifact content already verified).
- merge-sweep withheld `verified` on all three (exit-evidence tier
  undecidable for opencode lanes); verifiers re-run manually — pass.
  Comms posted on each card.
- tony-dell hygiene: orphan `runner-agent.service.d` drop-in with no
  unit; decide real unit vs manual-only runner (recorded in job doc gaps).

## Verify

- `git show origin/master:docs/reports/devnest-fl-pilot-1-doc.md` (5 headings)
- `python3 tests/ops/test_pilot_metrics.py` on master content — 3/3
- `python3 -m unittest tests.board.test_runner_agent_lane tests.board.test_merge_sweep`
- `docs/ssot/jobs/devnest/pilot-runs/2026-10-26-*.yml` — field→source schema
- `git merge-base --is-ancestor 874a9924 origin/master` — flips true after
  next merge-sweep tick once this branch lands
