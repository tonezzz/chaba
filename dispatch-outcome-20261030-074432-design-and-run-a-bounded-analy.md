# Dispatch outcome — OpenCode -> Cline proposal-workflow pilot

**Card:** `opencode-cline-idea-proposal-workflow` · **Runner:** mn01 · **Date:** 2026-10-30
**Result:** bounded analysis-only pilot executed; partial pass — shadow arm complete, live lane arm blocked at scheduler level.

## What changed (committed on this dispatch branch, ebee3d2bf)

- `docs/reports/2026-10-30-cline-proposal-pilot.md` — full pilot report (verification table, design, metrics, acceptance eval, recommendations).
- `docs/ssot/jobs/workflow/2026-10-30-cline-proposal-pilot.yml` — job trail with key findings.
- `evals/cline-proposal-pilot/` — versioned snapshot (sha256 `d4cc6b50…`, marker `SNAP-edu-no-th-v1:d4cc6b50`), manifest, intake draft JSON, shadow prompt + proposal + run meta.
- `docs/ssot/infrastructure/ssot.audit.hosts.yml` — declared `cline-intake.timer` in con01 expected_services (was deployed-but-undeclared).

## Verified live (before any run)

- Privacy boundary: unauth GET `/` and `/api/tasks` -> 401 on `100.72.146.39:3484` from mn01.
- Provider: Ollama `tony-omen:11434` live; qwen2.5:7b + qwen3:4b present (bridge allowlist: those + openrouter or-free-*, paid blocked).
- Submission path: `cline-intake.timer` -> `intake.py` -> `bridge.py` -> `podman exec kanban task create/start` on disposable `/workspace`; adapter proven by `cline-intake-smoke` (task 0bcda, real patch, 2026-10-29). The earlier "artifact contract not passed" hold note on the parent card is stale.

## Pilot execution

- **OpenCode role (intake):** structured draft via local Ollama qwen2.5:7b — 53.2s / 739 tokens. Correct goal + all constraints; weak done_condition, 1/3 useful missing questions. (opencode CLI absent on mn01 — substitution disclosed.)
- **Cline role (analysis):** shadow arm ran the exact wrapped lane prompt on mn01 — 157.2s / 1730 tokens, all 7 required sections, sentinel verbatim, **0 unsupported claims**, correct adjacent-not-duplicate call on `audit-miss-education-lesson-write-timeout`.
- **Live lane arm:** card `cline-proposal-pilot-edu-no-th` (DEV-1004) created via board-api, validated end-to-end offline (`intake.card_to_spec` + `bridge.validate_spec` PASS on the live card), sits at the queue head — **no pickup in >70 min**: `cline-intake.timer` is likely not enabled on con01 (the smoke's 17-min turnaround fits a manual run better than a live timer) and `chaba-repo-sync` is undeclared for con01. Needs `systemctl --user list-timers` on con01.

## Findings worth cards/follow-up

1. **Silent lane starvation:** `intake.py --limit 1` + alphabetical order = a `cline`-tagged card without lane config blocks every later card with zero board-visible signal. Live cases: `repo-choice-decision-policy` (starving since 09:01), `jack-llm-stack-agent-eval` (next blocker). Heads-up comments posted on both.
2. **Lane deliverables unreachable off con01** — reviewer can't see proposal content remotely; recommend excerpt-in-comment.
3. `intake.py` default `BOARD_API` still points at tony-dell (works, but misleading post-OPS-0725).
4. Duplicate result comments on the smoke card = overlapping intake executions, not a board-api bug.

## Board state / decisions

- Comments: progress + full results on the parent card; link notes on `cline-kanban-con01-pilot` + `cline-kanban-nest-worker-adapter`; starvation notes on the two blocking cards.
- **Open request:** `independent-review-needed-for-pilot-acce-231d62` — Tony's verdict on pilot pass + whether to update idea-intake/ai-lane-delegate procedures (deferred per spec — one pilot is not "repeatable").
- Card left **unqueued** — the live task path's scheduler is not yet verified.

## How to verify

- `git show ebee3d2bf` on the dispatch branch; read `docs/reports/2026-10-30-cline-proposal-pilot.md`.
- `curl -s http://100.72.146.39:3484/api/tasks` -> expect 401.
- Pilot lane card will complete autonomously whenever con01 intake actually runs: check `cline-proposal-pilot-edu-no-th` column/comments on the board.
- On con01: `systemctl --user list-timers cline-intake.timer chaba-repo-sync.timer` to close the arming question.
