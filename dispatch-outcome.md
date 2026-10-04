# Dispatch outcome — chaba-ci-standard

## What was built

The standard Chaba CI pipeline for card-sized work — five stages
(plan → structure → develop → audit → benchmark) that any kanban card
opts into via `pipeline: ci`.

**New files**
- `docs/ssot/ssot.ci.yml` — the declared standard: stage gates, required
  artifacts, status enum, opt-in/normalization, both write paths, and
  the dispatch wiring contract.
- `scripts/ci/card-pipeline.py` — the runner. Two sinks: `--cards-dir`
  file mode (direct YAML under `/tmp/board-api.lock`, the
  kanban-dispatch protocol) and `--api` mode (`/comment`, `/request`,
  new `/pipeline` endpoint; falls back to a structured comms line if the
  endpoint isn't deployed yet). `--selftest`, per-stage comms, request
  dedup/reopen, `reports/ci/<card>-<ts>.json` + meta/timeline.
- `tests/fixtures/tts-artifact-clean-transcript.txt` — the two observed
  artifact lines from transcript 519088cb6d; makes the card's metric
  greppable.
- `docs/ssot/jobs/workflow/2026-10-04-chaba-ci-pipeline.yml` — job trail.

**Modified**
- `scripts/board/board-api.py` — new `POST /pipeline` (opt_in, deep-merge
  status block, single-stage writes; selftest coverage added).
- `scripts/board/kanban-dispatch.py` — TASK_RAILS now tells sessions to
  run the runner via `--api` near the end when a card opts in.
- `docs/ssot/kanban/ssot.kanban.yml` — card_schema `pipeline` +
  `benchmark` fields; write_path documents `/pipeline`.
- `docs/ssot/infrastructure/ssot.reports.yml` — `ci-pipeline` L1 node
  (`reports/ci/`).
- `docs/ssot/infrastructure/ssot.quality.yml` — new `card-pipeline`
  lane + three registry entries (`gate.card-plan-structure`,
  `gate.card-audit`, `gate.card-benchmark`); related_ssot updated.
- `docs/ssot/kanban/cards/tts-artifact-clean.yml` — demo card: opted in,
  `action.repo: ada-pi`, `benchmark.command`, plus the run's
  `pipeline:` status block, comms, and two open requests.

## Demo result (tts-artifact-clean, file mode)

`plan=pass structure=pass develop=delegated audit=pass benchmark=blocked`
— audit ran 8 real checks on the worktree diff; benchmark recorded
`before: 2` from the fixture grep and raised a request for the `after`
measurement; develop was honestly delegated (card targets ada-pi, this
worktree is chaba) with a request raised. Run artifact:
`reports/ci/tts-artifact-clean-20261004-203950.json`. Re-run is
idempotent — requests dedup, `before` is never overwritten.

## How to verify

- `python3 scripts/board/board-api.py --selftest` → `selftest ok`
- `python3 scripts/ci/card-pipeline.py --selftest` → `selftest ok`
- `node scripts/ssot-validate-all.mjs` → 0 errors (2 pre-existing
  bloat-review warnings on quality/reports)
- Card `tts-artifact-clean.yml` shows the `pipeline:` block, two open
  requests, per-stage comms.

## Follow-ups (noted in the trail)

- Deploy the `/pipeline` endpoint to the live board-api (served
  checkout chaba-tony-dell) — until then api-mode falls back to a
  `pipeline-status:` comms line, nothing is lost.
- Dispatch `tts-artifact-clean` against ada-pi to satisfy the develop
  request, then re-run `--stages benchmark` for the after value.
- Live card `tts-artifact-clean` was deliberately NOT touched via the
  API — all demo writes are in the worktree file to avoid a cross-
  checkout merge conflict on the comms list.
