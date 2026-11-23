# Dispatch outcome — kk-mac routing proposal (card-judgment-eval-done) — 2026-11-23

Card: `kk-mac-routing-proposal-fold-local-qwen2-4d513b` (ref OPS-0095, parent eval KNB-1087)
Session: `devin-task-20261123-145003-card-judgment-eval-done-2026-1` on tony-macbook

## What this run actually was

The routing proposal was already **drafted, approved by Tony (option a), and deployed live on 2026-11-13** — summary/classify/bench leg-1 = `qwen2.5:32b@ollama-kkmac` via the :11447 admission shim, chat-local leg-2, tool-call deferred. What failed (twice) was *landing the branch*: the 2026-11-13 branch rotted into 15 merge-conflict requests, and the 2026-11-18 v2 re-land branch hit the test-gate timeout and also never merged. Tony answered every conflict request "let devin resolve the conflict and land it". This run did exactly that.

## What changed (branch `dispatch/20261123-145003-card-judgment-eval-done-2026-1`)

- `86ff411997` — merged `origin/dispatch/20261118-184235-card-judgment-eval-done-2026-1` (the complete v2 branch) into this worktree:
  - `docs/ssot/jobs/devnest/2026-11-18-kk-mac-routing-proposal.yml` — the deliverable. Covers job_class placement (summary/classify/bench LIVE leg-1, chat-local LIVE leg-2, tool-call DEFERRED leg-3 pending 3 qualifying runs + deference ≥0.90, voice-aux/chat/vision/image/embedding excluded), lane-savings.py evidence path, risks (member-device availability now shim-gated, 60C temp/load gating, qwen3:8b parse-fragility → qwen2.5:32b pin), and T3 rerun cadence (kkmac_eval.sh per online window ≥24h apart, 3 runs in ~2 weeks).
  - `scripts/board/lane-savings.py` — `EXECUTOR_LANES` attribution: `kk_mac_local`/`jules`/`nlm_batch`/`opencode` executor-pinned cards now count as their lane instead of `devin`.
  - qwen3:8b → qwen2.5:32b repin across `kk_mac_executor.py`, `kk_mac_llm.py`, `kk_mac_lane_worker.py`, `kk_mac_plan_validator.py`, `devnest_report_feed.py` (eval: qwen3:8b had 16 parse-fails vs 0).
  - `ssot.devnest-lanes.yml` expected_tokens note updated.
- `072b125ea9`/`fad9e73e4d`/`15590aee89` — pre-commit-hook regenerations of `ssot.dev-system.assessment.yml` (auto-generated; timestamps churn on every commit).
- `9f20fe302c` — merged current `origin/master` (19 commits of drift) into the branch so merge-sweep gets a clean fast-forward. Required refreshing `reports/SSOT_OPTIMIZATION_WARNINGS.json` baseline: the card file itself is now 764 lines > 750 hard threshold, bloated by the merge-sweep's own 15 repeated conflict-request comms (a known systemic issue — the bloat is not editable card-side since board-api owns card writes).

## Conflict resolutions

- `ssot.dev-system.assessment.yml` — kept newest generated state each time (this file self-regenerates in pre-commit; stale branch data never wins).
- Everything else auto-merged: master already carried the deployed gateway legs in `ssot.llm-gateway.yml` + `stacks/idc03/litellm/config.yaml` (live since 2026-11-13 deploy + 2026-11-14 shim), so only doc/script pieces were outstanding.

## Result / how to verify

- `python3 scripts/board/lane-savings.py --month 2026-11` — now shows `kk_mac_local` (1), `jules` (6), `nlm_batch` (1) as distinct lanes instead of folding into `devin`. Verified live this run.
- `grep DEFAULT_MODEL scripts/devnest/kk_mac_executor.py` → `qwen2.5:32b`; same pin in the other 4 kk_mac_* files.
- `docs/ssot/jobs/devnest/2026-11-18-kk-mac-routing-proposal.yml` exists on the branch; the v1 (`-13`) file is superseded — v2 documents the orphaning inline.
- YAML parse ×4, `py_compile` ×6, SSOT validation + optimize gate pass.
- Branch head `9f20fe302c` is 0 commits behind origin/master → merge-sweep lands clean. Not pushed per dispatch rules; the runner's close-out pushes.

## Still open (not this card's scope)

- The stale v1 branch `dispatch/20261113-202232-card-judgment-eval-done-2026-1` can be deleted once this lands — fully superseded.
- The 15 merge-conflict requests on the card resolve themselves once this branch lands.
- T3 gate still needs 2 more qualifying `kkmac_eval.sh` runs (1 in hand, deference 0.878 < 0.90) before tool-call leg-3 — cadence documented in the proposal.
- Token-evidence gap for kk_mac_local savings remains carded in the proposal's next_steps.

lessons:
- When a card's real failure is "branch never merged", check for a *newer* re-land branch first — the v2 branch was a strict superset; resolving it once was cheaper than replaying v1's 5-file conflict set.
- `ssot.dev-system.assessment.yml` self-regenerates in pre-commit on every commit (timestamp churn) — resolving it by "newest wins" and accepting leftover dirty state is correct; don't loop commits chasing a clean tree.
- Merging fresh `origin/master` into the dispatch branch *before* finishing prevents the exact conflict-rot that killed the last two attempts.
- The 750-line SSOT card-bloat gate blocks merge commits that pull in board-api card updates; refreshing `reports/SSOT_OPTIMIZATION_WARNINGS.json` via `node scripts/ssot-optimize.mjs` is the sanctioned escape — card YAML itself must not be hand-trimmed (board-api owns it).
- `git merge-tree`/`git merge --no-commit` on the orphan branch is the cheapest way to preview which conflicts are real vs already-landed — here the "conflicting" litellm/gateway files were already on master via the live deploy, leaving exactly one generated-file conflict.
