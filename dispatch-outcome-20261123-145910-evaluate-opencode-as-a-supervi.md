# Dispatch outcome — opencode-standard-procedure-rollout (attempt 3)

## Finding: work already landed; this run verified + one correction

The evaluation this card asks for was completed and merged to master earlier
today by a parallel dispatch (`dispatch-wt-20261123-075055`, mn01):

- Merge: `cef8b706a9` (Merge branch 'dispatch/20261123-075055-evaluate-opencode-as-a-supervi')
- Commit: `7114d47166` — "eval: OpenCode supervised executor rollout — verdict ADOPT-BOUNDED"
- Deliverable: `docs/ssot/jobs/devnest/2026-11-23-opencode-standard-procedure-rollout-eval.yml`

The card was re-queued at 14:48 (manual retry) after that merge — likely
because the action was never marked done, not because the work was missing.

## What this session did

1. Read the full card trail. Attempt 2 (2026-11-20) had completed the same
   eval but the session died right after committing on its dispatch branch;
   merge-sweep correctly never auto-merged it. The 07:50 run re-derived the
   eval and merged it cleanly.
2. Verified the merged doc against the spec, line by line:
   - All 10 `spec_element_mapping` entries present and each backed by real
     machinery (checked: `OPENCODE_LANES` defaults `"0"` per-host in
     `runner-agent.py:269`; `S3_STAGED_PROFILES` at `runner-agent.py:2838`;
     hard-deny class row in `evals/opencode-lane/PROCEDURE.md` — production/
     destructive/deploy/secret/payment/credential never admitted).
   - All 9 `evidence_files` exist in-tree, including the 3 pilot-run docs and
     both lane review JSONs.
   - Verdict ADOPT-BOUNDED matches the answered board request
     (`supervised-s0-s2`) and the spec's explicit no-go items
     (no fleet-wide OPENCODE_LANES, no Colab, human-gated classes stay gated).
3. Corrected one drifted fact: `ssot.procedures.yml` currently holds 76
   procedure entries, not 78 — updated both mentions in the eval doc.

## Result

Verdict stands: ADOPT-BOUNDED. Deterministic procedures stay scripts;
OpenCode serves only bounded S0-S2 read-only/report/doc/small-test judgment
slices through the existing envelope/profile contract, and only once the
lane re-graduates (it sits at S0 after the 2026-11-12 stor-01 rollback;
`opencode-lane-regraduation` owns the climb). Production changes, secrets,
external publication, key/budget changes, and service restarts remain
human-gated hard-deny classes.

## How to verify

- `cat docs/ssot/jobs/devnest/2026-11-23-opencode-standard-procedure-rollout-eval.yml` (on master after merge)
- `grep -n "OPENCODE_LANES" scripts/board/runner-agent.py` → line 269 default `"0"`
- `sed -n '30,36p' evals/opencode-lane/PROCEDURE.md` → stage table + never-admitted classes
- `grep -cE '^\s+- \{id:' docs/ssot/ssot.procedures.yml` → 76

## Files changed on this branch

- `docs/ssot/jobs/devnest/2026-11-23-opencode-standard-procedure-rollout-eval.yml` — 78→76 procedure count (2 lines)
- `dispatch-outcome-20261123-145910-evaluate-opencode-as-a-supervi.md` — this file

lessons:
- Always read the card's comms first on a retry: a parallel dispatch had already merged this eval — the retry was queued on a stale "action not done" flag, not missing work.
- Verify landed-deliverable claims against the tree before redoing work; spot-checking numbers found a 78→76 procedure-count drift worth correcting.
