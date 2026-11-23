# Dispatch outcome — kk-mac-extract-brief-class-eval

Date: 2026-11-23 · Host: mn01 · Branch: dispatch/20261123-134412-the-kk-mac-local-lane-admits-4
Commit: d767d24848

## What happened

This card's work was already done twice but never landed:

- 2026-11-19 (tony-omen): full eval built + run live on kk-mac —
  51-case corpus, score.py on the production path, 3 model reports.
  Session exited ok but the checkpoint commit failed (worktree 114
  commits behind origin/master); 12 files left uncommitted, later lost
  to merge-sweep.
- 2026-11-23 attempt 2 (tony-dell): recovered the work intact into its
  worktree; service died on provider rate-limit before committing.
- 2026-11-23 attempt 3 (tony-macbook): committed it locally as
  6126adaf36 — that commit was never pushed (not on origin) and died
  with the rate-limited service.

This run (mn01) recovered the complete deliverable from the still-present
tony-dell attempt-2 worktree via ssh/scp, re-verified it against CURRENT
production code, and committed it.

## Deliverables (all committed)

- `scripts/bench/kkmac-classes/` — build_corpus.py, corpus.jsonl
  (51 cases: 15 structured_extract / 16 operator_brief / 15 safe_route
  + 5 summary controls), score.py, kkmac_eval.sh, and the three live
  run reports (run-kkmac-{qwen38b,qwen2532b,llama323b}.{md,json}).
- `docs/ssot/jobs/devnest/2026-11-19-kkmac-class-eval.yml` — job record
  with method, per-model results, findings, decision (added required
  `title` field + `recovered:` note for the SSOT pre-commit gate).

## Verification done here

- `build_corpus.py` regenerates corpus.jsonl byte-identical (md5 match).
- `score.py --entity mock-oracle`: 51/51 cases pass
  kk_mac_executor.verify — corpus + verifier contract healthy against
  current master (call_remote/verify signatures unchanged).
- Live kk-mac re-run NOT possible from mn01 (ssh kkkakk@kk-mac times
  out — node asleep/unreachable); not needed — the committed run-*.md
  reports ARE the live results from 2026-11-19/23, gates fail closed by
  design so the harness is safe to re-run from any tailnet host.

## Eval result (the card's question: can these classes take real inbox work?)

- structured_extract: READY — 0.93-1.00 pass on all 3 models; JSON
  compliance ~100%, only fact-echo misses.
- operator_brief: marginal/not ready — 0.31-0.56; schema perfect but
  briefs drop facts producers declared.
- safe_route: NOT ready — 0.33-0.60; every model fails differently
  (qwen3:8b over-defers, llama3.2:3b over-acts incl. unsafe picks,
  qwen2.5:32b over-observes). Model size does not rescue it.
- summary control also ~0.4-0.6 — fact-echo strictness affects even
  the production class; expect.facts must be literal output tokens.

Full numbers + decision in the job yml.

## How to verify

```
python3 scripts/bench/kkmac-classes/build_corpus.py   # rewrites corpus.jsonl
python3 scripts/bench/kkmac-classes/score.py --entity mock-oracle  # 51/51 pass
scripts/bench/kkmac-classes/kkmac_eval.sh qwen3:8b   # live re-run (needs awake kk-mac)
```

## Lessons

- Dispatch work that "finished ok" can still be lost if the checkpoint
  commit fails on a stale worktree — recovered here only because the
  sibling worktree survived; pushing the dispatch branch earlier would
  have made this trivial.
- Commit 6126adaf36 existed only on tony-macbook's local worktree and
  died unpushed — local commits on dispatch branches are not durable
  until the runner pushes.
- docs/ssot/jobs/*.yml requires a `title:` field — the SSOT pre-commit
  gate rejects without it.
- mn01 cannot reach kk-mac over tailnet ssh (timeout) — bench harnesses
  must run from hosts with kk-mac ssh config (tony-dell/omen worked).
