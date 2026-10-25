# Dispatch outcome — devnest-kanban-next-wave priority sequence (KNB-0856)

Session: dispatch-wt-20261025-124112-priority-sequence-1-ops-0846-o on mn01.
Card: `devnest-kanban-next-wave`. Ledger (per-step artifact/verifier/
rollback): `docs/ssot/jobs/nest/2026-10-25-devnest-next-wave-ledger.yml`.

## What changed (this branch)

- `scripts/board/runner-agent.py` — **bug fix**: `lane` was unbound in
  `start_task` whenever a card already carried `action.lane` (explicit
  lane or the JEV_LANE claim-classify persist) → UnboundLocalError
  crashed the claim before any unit spawned (since f9882330). Now bound
  from `a.get("lane")` first; classified-manual is refused loudly;
  `start_opencode_lane` meta.json gains `base`/`executor`/`started_at`
  parity with devin-dispatch `_meta_write`.
- `tests/board/test_runner_agent_lane.py` — 5 regression cases for the
  lane branch (explicit-lane devin path, explicit→opencode, unset-lane
  classify+persist, classified-free→opencode, classified-manual refuse).
- `scripts/ops/decision-arena.py` — corpus v1→v2: 27→**50 labeled cases**
  (confirm 12 / tool 16 / pipe 10 / stag 12; noul 17/17; pipe gained
  invalid edges — v1 was single-class). Added `--corpus-only` verifier,
  `--out` per-case records, env-overridable backend URLs, real
  dead-backend ping gate, laya single-load.
- `scripts/lessons-drift.py` — **new** read-only source-doc freshness
  check over board-api `/lesson` (drift / source-gone / no-repo-source;
  `--strict`, `--slugs`, `--out`, `--repo`).
- `evals/results/jev/decision-arena-50.json` — per-case raw records.
- `reports/2026-10-25-decision-arena-50.md`, `reports/2026-10-25-lessons-drift.{md,json}`.

## Results per step

1. **OPS-0846 closeout** — code-complete + unit-verified; NOT yet
   end-to-end verified. Live findings: idc02 `jev-lane.conf` is
   malformed (`Assignment outside of section` — env inert), idc02 load
   ~9.2 → `overloaded()` holds all claims (why OPS-0870 sits queued).
   Gates are effectively OFF fleet-wide — safe.
2. **OpenHands GUI** — ran on tony-dell vs `~/devnest-sample`:
   `openhands --override-with-envs web` served HTTP 200; agent loop
   verified headless (11 msgs, `litellm_proxy/bench`, README
   Architecture section, `node test.js` green, no git ops); server
   stopped. Gotcha: bare `LLM_*` env ignored, flag must precede
   subcommand. Card comm posted to `eval-ide-openhands-gui`.
3. **JEV arena** — 50-case corpus landed; jev-student run: **0.480 acc /
   0.676 noul / 0.062 choice** — choice head confirmed dead at scale
   (15/16 → "answer"); pipe rubber-stamps false; stag under-detects;
   confirm 12/12. jevos arm unreachable from mn01 — must re-run on
   idc03 for the routing-gate number. Card comm posted.
4. **Lesson drift** — first live audit: 77 lessons → **1 drifted, 36
   source-gone** (~28 point at never-committed `docs/tools/*.md` —
   broken pointers), 38 no-repo-source.
5. **OPENCODE_LANES** — **stopped at the gate by design**: probe
   unverified + fixed code undeployed + conf inert → enabling would
   crash claims. Enable runbook is step 5 of the ledger.

## How to verify

- `python3 -m unittest discover -s tests/board -t .` → 191+5 tests OK.
- `python3 scripts/ops/decision-arena.py --corpus-only` → total 50,
  errors=[].
- `python3 scripts/lessons-drift.py --out /tmp/d.json` → counts match
  board-api op=list.
- OPS-0870 (`opencode-closeout-probe-idc02`) card comms → claim +
  merged outcome once idc02 load drops and this branch deploys.

## Not done / handoff

- End-to-end opencode closeout verification (blocked on idc02 load +
  this branch merging + runner-agent redeploy).
- jevos arm on idc03 (routing-gate input for BEN-0826).
- Broken `docs/tools/*` lesson pointers (~28) — commit the docs or
  re-file lessons.
- lessons-drift periodic wiring — new card if wanted.
