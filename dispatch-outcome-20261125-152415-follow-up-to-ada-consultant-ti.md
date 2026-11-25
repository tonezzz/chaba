# Dispatch outcome — consultant-brain-confirmation-bench (2026-11-25)

## Result

**qwen2.5:32b CERTIFIED as the consultant brain. qwen3:8b DISQUALIFIED.**

Fresh x3 confirmation series on the CORRECTED corpus (observe-006
relabelled observe->defer, ported from stranded commit 2ad449c283) ran
against kk-mac ollama (`http://kk-mac:11434/v1`, temp 0.3, max-tokens
2048, --entity ada --enforce --briefs briefs.json, 94 cases):

| model | run | acc | deference | corr_prec | defer->act/correct |
|---|---|---|---|---|---|
| qwen3:8b | 1 | .9043 | .9255 | .8824 | 3 (defer-027->act, defer-013/009->correct) |
| qwen3:8b | 2 | .9043 | .9574 | .8571 | 3 (defer-027->act, defer-009/028->correct) |
| qwen3:8b | 3 | .8511 | .9149 | .8108 | 7 |
| qwen2.5:32b | 1 | .8936 | .9468 | .8571 | 0 |
| qwen2.5:32b | 2 | .8936 | .9468 | .8571 | 0 |
| qwen2.5:32b | 3 | .8936 | .9362 | .8824 | 0 |

- qwen3:8b hit the letter of the 3x-consecutive metric gate AGAIN but
  every run over-acts on defer-golds; defer-027->act and
  defer-009->correct recur in all three runs — systematic, not
  temperature variance. Disqualified per the card's rule (over-act is
  the disqualifying direction).
- qwen2.5:32b: 3 consecutive clean passes, zero over-act in any run.
  acc identical (.8936) across runs — deterministic on this corpus.
  Its misses are the benign direction (act->defer, observe->defer).
  The spec's "one probe run" was extended to x3 after run1 came back
  clean — the streak is what certifies.

## What changed (all on dispatch/20261125-152415-follow-up-to-ada-consultant-ti)

- `git merge origin/master` — worktree was 837 commits behind; merged
  cleanly so closeout merge is trivial.
- `git merge origin/dispatch/20261119-130719-tiered-judgment-instead-of-ada`
  — the consultant LANE itself was still unmerged (only conflict:
  generated `docs/ssot/generated/jobs.idc03.yml`, regenerated via
  `scripts/render-jobs.py --host idc03`). Lane now lands on master at
  closeout: consultant_worker.py, verify_worker --consultant,
  board-api ACTORS+=consultant, ssot.jobs.yml ada-jobs-consultant,
  rendered idc03 units, litellm model_name consultant -> qwen2.5:32b.
- Ported bench fixes from 2ad449c283: score.py `--max-tokens`,
  corpus.jsonl + corpus-v4.jsonl observe-006->defer relabel,
  consultant-corpus-audit-2026-11-19.md.
- 6 result artifact pairs: `scripts/bench/card-judgment/consultant-confirm-qwen38b-run{1,2,3}.{md,json}`
  and `consultant-confirm-qwen2532b-run{1,2,3}.{md,json}`.
- Job trail: `docs/ssot/jobs/bench/2026-11-25-consultant-confirmation-bench.yml`.
- SSOT truth updates: `ssot.ada-participation.yml` consultant_tier.status
  -> certified-pending-activation; litellm config comment updated.

## Verification done

- `tests/ops/test_render_jobs.py` — 27/27 pass (generated tree matches
  ssot.jobs.yml incl. ada-jobs-consultant).
- `board-api.py --selftest` — ok (consultant ACTORS paths exercised).
- `py_compile` on consultant_worker/verify_worker/board-api/score — ok.
- consultant_worker --help / verify_worker --consultant flag present.
- idc03 checked: ssh works, ada-jobs-verify.timer active, no consultant
  units yet (expected pre-merge). Admission-shim :11447 currently returns
  `admission_denied: temp_high` — kk-mac thermals after the bench series;
  the shim gates by design and will admit when cool.

## NOT done — activation (needs the merge on master first)

The spec's "if certified" clause authorized flipping
ADA_JOBS_CONSULTANT=1 + installing ada-jobs-consultant units on idc03,
but idc03's exec checkout only sees origin/master — which happens at
closeout auto-merge + chaba-repo-sync, i.e. after this session ends.
Remaining steps (full runbook in the job doc):

1. idc03 chaba-repo-sync pulls master (15-min cadence on idc03).
2. Install `systemd/generated/idc03/ada-jobs-consultant.{service,timer}`.
3. board-api restart (ACTORS += consultant takes effect).
4. litellm reload (model_name consultant -> qwen2.5:32b already configured).
5. `ADA_JOBS_CONSULTANT=1` on verify-worker env + daemon-reload + restart
   ada-jobs-verify.

Watch item: consultant_worker uses max_tokens=800 temp=0 (bench used
2048/temp 0.3) — fine for non-thinking qwen2.5 but worth an eyeball on
first live verdicts.

lessons:
- Dispatch worktrees can be hundreds of commits behind origin/master — merge origin/master into the branch BEFORE merging feature branches, or closeout's merge --no-ff hits unresolvable conflicts outside the auto-resolve paths (generated/cards/scratch).
- `git merge` of two dispatch branches conflicts on generated/* files even when content is right — resolve by re-running the generator (render-jobs.py), not by picking a side.
- Plain-scalar YAML keys/values can't contain ": " — job-doc prose with "Models present: x" fails the pre-commit SSOT gate; use folded scalars (>-).
- score.py --max-tokens was stranded on an unmerged branch for 6 days; the corrected corpus existed nowhere on master — always check `git branch -r --contains` before assuming bench state.
- Running two ollama models concurrently on kk-mac roughly halves per-case throughput but finishes both series sooner overall; /api/ps shows only the last-loaded model — eviction is normal, not a failure.
