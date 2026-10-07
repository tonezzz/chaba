# expected-goals-verify — card acceptance via executable goals

## What changed

- **`scripts/lib/goals.py`** (new) — shared check grammar + executor.
  `http <code> <url>`, `command <shell> [expect <substr|exit [N]>]`,
  `file-exists <path>`, `git-ancestor <branch> <base>`, `ws <url>`
  (real RFC6455 handshake, pass on 101). `validate_goals()` normalizes a
  card's `expected_goals` and rejects prose — anything unparseable is an
  error list, not a goal. `--selftest` included.
- **`scripts/ci/card-pipeline.py`** — sixth stage `verify`: runs every
  goal in the session worktree, writes `pipeline.verify {at, ok: "n/m",
  goals: [{id, ok, evidence, at}]}`; any failure = stage `fail`.
  Plan gate now rejects prose goals outright and accepts valid
  `expected_goals` as the acceptance signal. `benchmark` skips cleanly
  when a card declares goals (goals are the acceptance — no spurious
  "declare a metric" request). `ApiSink.set_pipeline` retries without
  unknown stage names when board-api predates them (400 fallback,
  complements the existing 404 one).
- **`scripts/board/board-api.py`** — `"verify"` added to
  `PIPELINE_STAGES`.
- **`scripts/render-board.py`** — when `pipeline.verify.goals` exist,
  a `verify` summary chip + `goal:<id>` chips replace the outcome/deploy
  comms heuristics; git-reality chips stay. Chips show on running cards
  once goal evidence exists.
- **`scripts/report/report-watch.py`** — re-probes `expected_goals` on
  done cards every 24h (`GOAL_PROBE_H`) against the served checkout;
  regressions raise `report-watch-goal-rot-<card>` focus-inbox items;
  probe state in `reports/report-watch/state.json`.
- **SSOT**: `ssot.kanban.yml` (expected_goals + pipeline.verify schema),
  `ssot.ci.yml` (verify stage, companion field), `ssot.quality.yml`
  (gate.card-verify, six-stage lane). Job trail:
  `docs/ssot/jobs/kanban/2026-10-07-expected-goals-verify.yml`.

## Demo (end-to-end, first real ci-pipeline run)

Card `expected-goals-verify` itself opted in (`pipeline: ci`) and carries
5 goals (schema grep, two selftests, `file-exists reports/ci/meta.yml`,
board-api health HTTP 200). Ran all six stages via `--api` from this
worktree:

```
plan=pass structure=pass develop=pass audit=pass(9 checks/8 files)
benchmark=skip verify=pass (5/5 goals)
```

`pipeline.verify` is on the live card; run artifact +
`reports/ci/meta.yml` + timeline event written (the ci-pipeline node is
no longer `missing`). Worktree render shows `verify 5/5` + `goal:*` chips.

## Caveats

- Live board-api predates the `verify` stage name → `stages.verify` was
  dropped from the /pipeline write (graceful fallback, comms noted);
  `pipeline.verify` itself landed. `stages.verify` records once
  board-api.py merges + deploys.
- Goal chips render on the live board once render-board.py is promoted
  (served checkout) — not deployed in this session.
- `command`/`file-exists`/`git-ancestor` goals evaluate in the runner's
  worktree; report-watch re-probes evaluate in the served checkout.

## Verify

```
python3 scripts/lib/goals.py --selftest
python3 scripts/ci/card-pipeline.py --selftest
python3 scripts/board/board-api.py --selftest
node scripts/ssot-validate-all.mjs
```
