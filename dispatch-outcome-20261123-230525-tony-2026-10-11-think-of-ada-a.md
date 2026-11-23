# Dispatch outcome — ai-engine-lines (attempt 2, tony-macbook)

## What happened

Attempt 1 (mn01, 2026-11-23 22:28) died on a provider rate-limit after ~2min —
no work produced. This attempt picked up the real state:

- The card's deliverable — the engine=lane formalization — already existed
  in reviewed form on `origin/docs/ops-0466-engine-lines` (commit 568e50410a,
  PR #181) and in older salvaged form on the triage branch
  `dispatch/20261123-144247` (commit 94f51a5410). **Neither was in master.**
- Precondition is met: `line-multihome-group` is done/archived — the mention
  router proves per-lane isolated WS backends.
- Tony's naming decision (codename-per-line, functional IDs stable) was
  already recorded in the 568e version — used that as the base.

## What changed (commit 40bde32df1 on dispatch/20261123-230525-...)

- `docs/ssot/apps/ssot.apps.ada-engines.yml` (new, ~265 lines): the formalized
  model — terms (lane / engine / engine_line / engine_release / contract),
  contract v1 fixed surface (WS + /api/health + /api/auth/*, caller keys,
  server-side tier policy, per-sender sessions, relay-only proactive,
  loud-fail capabilities), engine registry (ada-1 live fleet-wide; ada-2,
  chaba-ops-0, edge-0 proposed), lane bindings, release model (config swap),
  versioning scheme, naming decision, gaps→cards.
- `docs/ssot/jobs/ada/2026-11-17-ai-engine-lines.yml` (new): design record +
  `refresh_2026_11_23` section documenting this re-landing.
- Refresh vs the PR #181 version: `last_updated` → 2026-11-23; lane_bindings
  re-verified against the grand-rename runbook's live idc03 audit — each
  binding now carries `unit` + `rename_to` (grand-rename in flight,
  family-first `ada-ai-<role>` gated on scheme reconfirm); lane ids
  documented as the stable contract keys; `ada-pi-pwa` retired note corrected
  to confirmed-retired (was an open caveat); release-model pointer list
  extended with `/ai/<role>` aliases; chaba-guest's separate tony-dell deploy
  and the planned idc03 `ada-guest` lane noted; `runs_on` corrected (chaba-guest
  is not on the idc03 shared checkout).

## Verification

- `node scripts/ssot-validate-all.mjs`: 5805/5805 valid, 0 errors (289
  pre-existing warnings).
- `python3 scripts/ssot-prose-smell.py`: 0 flagged.
- `python3 scripts/ssot-validate-refs.py`: no broken refs.
- Pre-commit hooks (SSOT validation + optimize gate): passed.
- Both YAML files parse clean; both new files individually `✅ Valid`.

## Follow-ups (all already carded — nothing new filed)

- `ada-engine-self-report`, `ada-engine-contract-suite`,
  `ada-engine-runtimes` — backlog.
- `persona-ab-split-routing-relay`, `ada-text-model-promotion-path` — backlog.
- PR #181 (`docs/ops-0466-engine-lines`) and triage branch
  `dispatch/20261123-144247` are now redundant — noted on the card for
  cleanup.

## How to verify

- Read `docs/ssot/apps/ssot.apps.ada-engines.yml` on this branch (or master
  after merge-sweep).
- Cross-check `lane_bindings` against
  `docs/ssot/jobs/ada/2026-11-23-grand-rename-execution-runbook.yml`
  `live_lanes` (SSH-verified idc03 audit, 2026-11-23).

lessons:
- Vision/design cards can sit "done" in comms while the actual deliverable
  files live only on unmerged dispatch/docs branches — always check
  `git branch -a --contains <commit>` and `git ls-tree origin/master`
  before assuming work landed; salvage branches are not merges.
- When re-landing salvaged work, diff candidate versions first: the
  docs/ops-0466-engine-lines version had Tony's answered decision baked in;
  the triage salvage was an older draft still showing the request as open.
- Multi-line plain YAML scalars need `>-` or deeper indent — a two-line
  continuation at key indent fails scanning (cost one validate cycle).
- The grand-rename runbook (jobs/ada/2026-11-23) is the freshest verified
  lane inventory — prefer it over ssot.apps.ada-persona-lanes.yml, which is
  stale (2026-10-13, still says ada-guest PLANNED, has a duplicate `ada-kk:`
  key that YAML silently dedupes).
