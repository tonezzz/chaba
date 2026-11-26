# Dispatch outcome — nest-job-done-evidence-gate (OPS-0923)

Review and harden the runtime job status contract after the OPS-0922
lifecycle SOP. Read-only reconciliation only — no auto-cancel, no claim
clears, no deploy, no production status mutation.

## What changed

**`scripts/board/board-api.py`** — the write-door contract:

- `JOB_TRANSITIONS` map + guard in `do_job`: status writes must follow
  the SOP transition table. Terminal `done`/`cancelled` exit only via
  `queued` (requeue) or `failed` (honest correction). Same-status
  rewrites and status-less comms updates always pass; unknown prior
  status imposes no constraint. Violations → HTTP 400 before any WP
  write.
- Terminal-done gate: `status=done` requires `result_ref` (durable
  pointer — body, stored meta, or `meta.result_ref`) AND verified
  artifact evidence (`evidence[]` refs, `verified:true`,
  `artifact_verified`, or `confidence=verified`). Accepted evidence
  persists to `meta.evidence` + `meta.artifact_verified=true`.
- `_pub_job_send` rewritten: job sink fires only for explicit `job`
  refs (previously fell back to `project`/`card` — every
  runner-lifecycle milestone was minting a `nest_job` post);
  `milestone` no longer implies `done` (the silent-completion bug);
  `progress`→`running`, `alert`→`stalled` remain; `meta.job_status` is
  the explicit override; `evidence[]`/`confidence=verified` pass
  through (`result_ref` defaults to `evidence[0]`); `do_job`
  ValueError → `pub.Skip` (never outbox-retried, siblings still
  deliver).
- New `GET /nest-jobs?slug=&limit=&comms=1` — read-only mirror listing
  for reconciliation (comms stripped unless `comms=1`, ≤500 cap).

**`scripts/ops/nest-job-reconcile.py`** (new) — read-only
cross-surface consistency check: WP `nest_job` meta vs `packs/*/done` +
`claim/` markers vs `queue/packs-index` fold vs `queue/lease`.
Pure `reconcile()` core + thin rclone/HTTP collectors. Finding codes:
`DONE-NO-RESULT-REF` (error), `DONE-UNVERIFIED`, `DONE-NO-PACK-MARKER`,
`PACK-DONE-JOB-NOT-DONE`, `PACK-FAILED-JOB-INCONSISTENT`,
`ACTIVE-JOB-PACK-TERMINAL`, `CANCELLED-LINGER-CLAIM`,
`LEASE-ACTIVE-TERMINAL-JOB`, `LEASE-STALE-WITH-ACTIVE-JOBS` (warn),
`ACTIVE-NO-CLAIM`, `PACK-TERMINAL-NO-JOB` (info). Never mutates.

**Tests** — `tests/board/test_board_api_mutations.py` (+7 contract
tests), `tests/board/test_publication.py` (+5 sink tests),
`tests/ops/test_nest_job_reconcile.py` (new, 15 tests). Selftest
updated for the new contract.

**Docs/SSOT** — `job-package-status-sop.md` §5 enforcement,
`colab-mcp-jobs.md` new `job-status-lifecycle-and-storage-map` section
(the card's link target), `board-api-write-door.md` `/job` + `/publish`
contract + `/nest-jobs`, `ssot.procedures.yml` `nest-job-reconcile`
entry, `docs/ssot/jobs/nest/2026-11-24-nest-job-done-evidence-gate.yml`.

## Result

Committed `f407b35f0f` on `dispatch/20261124-165943-…` — repo landing
only, not pushed, not deployed.

Verified: 130 focused tests pass; `board-api.py --selftest` ok;
`nest-job-reconcile.py` smoke-tested against fixture jobs.

## Deployment notes / follow-ups

- **board-api deploy activates the gate.** The external queue-mgr
  daemon (dell, not in this repo) mirrors Drive state via `POST /job`:
  its `done` writes must start sending `result_ref` +
  `evidence[]`/`verified` or they will 400. Until queue-mgr is updated,
  `nest-job-reconcile.py` findings are the drift signal. This is the
  intended forcing function — but it is a real deploy-ordering
  dependency worth a card if none exists.
- **Pre-existing suite failures (unrelated, present at base):**
  `test_control_pane_projection` (card YAML archived upstream in
  bc732b0cce) and `test_runner_tooling_contract` pin drift —
  `runner-agent.py` changed upstream without a manifest bump. Not
  fixed here (out of scope; pin bump would bless an unreviewed
  runner-agent change).

## How to verify

```bash
python3 -m pytest tests/board/test_board_api_mutations.py \
  tests/board/test_publication.py tests/ops/test_nest_job_reconcile.py -q
python3 scripts/board/board-api.py --selftest
python3 scripts/ops/nest-job-reconcile.py --api \
  https://idc03.taila0626a.ts.net:10000 --json   # needs rclone for Drive side
```

lessons:
- `_pub_job_send` used `ev["job"] or ev["project"] or ev["card"]` — every card-scoped lifecycle milestone minted a nest_job post AND milestone implied status=done. Two silent-completion bugs in one line each; always check sink fallback chains.
- board-api `--selftest` and mutation tests encode the OLD contract — grep tests for `status.*done` before changing write-door semantics or the suite fails in non-obvious places.
- `tests/board/test_runner_tooling_contract.py` pins sha256 of deployable single-file tools — unrelated upstream edits can fail the suite; check `git status` before assuming your diff broke it.
- The WP `nest_job` mirror's real writer (queue-mgr) lives outside this repo — contract changes need a deploy-ordering note or the mirror stalls at running.
