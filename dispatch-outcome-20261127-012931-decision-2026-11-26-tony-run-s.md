# Dispatch outcome — 20261127-012931 decision-2026-11-26-tony-run-s

Card: `opencode-lane-regraduation` — DECISION 2026-11-26 Tony: run S1 then S2, hold S5.
Attempt 10 (attempts 1–9 all ended blocked on the same provider-quota wall or
unmerged; the prompt's "attempt 2 / previous run did not merge" = the recurring
unmerged-evidence pattern, not a new code failure).

## Result: BLOCKED — unchanged provider-quota blocker, verified live, evidence secured

No stage change, no requalify, no ledger writes, no model admissions. ~5.4h to
the OpenRouter free-tier reset (07:00 +07); S1 additionally needs Tony's live
watch regardless of quota.

### Verified live state (idc02, ~01:32–01:35 +07)

- Lane `current_stage: S0`; qualification boundary 2026-11-26T15:58:36Z
  (`devin-for-tony`, OPS-1363 epoch-pollution adjudication); `jobs_completed
  {S0: 5}` = attempt-2's banked provider-outage fails — metrics.jsonl mtime
  Nov-26 23:23 unchanged (last rows still the 16:19Z s0-worktree-safety pair).
  Any retry climb needs requalify #2 first (incident review =
  `evals/opencode-lane/reports/2026-11-26-promotion-review-s0-provider-outage.json`).
- Fresh gate evidence this session: `python3 scripts/devnest/lane_gate.py review`
  @2026-11-26T18:34:48Z → `decision=hold`, `verified rate 0.0 < 0.6`, jobs=5,
  verified=0, escalations=5, `human_minutes_total=0`,
  `failure_reasons={missing_artifact:5}` — provider outage, NOT a safety
  rollback. Written to `evals/opencode-lane/reports/2026-11-27-promotion-review.{json,md}`.
- S1 canary staging intact: `~/.local/state/opencode-lane/s1-watch.sh` (966B exec,
  mtime Nov-26 23:02) + `staged-jobs/s1-opsread-regrad-20261126.yaml`;
  `inflight/` empty. runner-agent.timer active (last tick 01:33:53 +07,
  ~50s before probe).

### Quota probe (2026-11-26T18:33–18:34Z, 8-token POSTs via litellm proxy) — unchanged wall

- `or-free-nemotron-ultra` (the pinned qualification/S1 model): HTTP 429
  `free-models-per-day-high-balance` — OpenRouter account-wide daily cap,
  `X-RateLimit-Reset=1795737600000` = 2026-11-27T00:00Z = **07:00 +07**.
- `gemini-2.5-flash-lite`: HTTP 200 in **3.2s** — 5th consecutive responsive
  probe. Whether it is AI-Studio free-tier or metered is unverified; switching
  the qualification model is Tony's call either way (request option B — and if
  metered it is also spend).
- `agent-local` (qwen2.5:7b): HTTP 200 in **24.5s** — responsive but slow;
  historically flaky in-lane (timeouts, shared-checkout scope_violation false
  positives). Still Tony's call.
- Zen free remains inside its ~8.6h retryAfter window (~08:00 +07); gemini
  `*-free` pools capped until ~15:00 +07 per attempt-5.

### Board state

- Request `free-lane-providers-quota-capped-until-0-169f8f` still `status: open` —
  Tony has not picked A (wait-for-reset) / B (alternate model) / C (hold).
- `answers.jsonl` carried only the recurring junk `answer — Answer — reply in
  chat` echo from ada (18:29Z). needs-input.txt written with the same question +
  this probe's evidence.

### What changed in the repo (this branch `dispatch/20261127-012931-…`)

- Carried forward **file-identical** all evidence files from local branch
  `dispatch/20261127-011421-decision-2026-11-26-tony-run-s` (itself carrying
  attempts 1–9): 9 dispatch-outcome mds,
  `docs/ssot/jobs/devnest/2026-11-26-opencode-lane-s1-gate-state.yml`,
  `evals/opencode-lane/jobs/s1-opsread-regrad-20261126.yaml`, and the
  2026-11-26 promotion-review pairs (rollback + s0-provider-outage) — because
  **none of it is on origin/master** (this branch forked at 09e514c5b0 whose
  evals/opencode-lane/reports/ ends at 2026-11-12).
- Deliberately NOT carried: attempt-9's `2026-11-27-promotion-review.{json,md}`
  (this session's fresh pair supersedes) and `ssot.dev-system.assessment.yml`
  (pre-commit hook churn).
- Added fresh `evals/opencode-lane/reports/2026-11-27-promotion-review.{json,md}`
  from this session's `lane_gate.py review`.
- Trail doc: appended `attempt_10_2026_11_27_012931` section.

## How to verify

- `git show --stat HEAD` on this branch; files under `evals/opencode-lane/reports/2026-11-26-*`
  and `2026-11-27-*`, `evals/opencode-lane/jobs/s1-opsread-regrad-20261126.yaml`,
  `docs/ssot/jobs/devnest/2026-11-26-opencode-lane-s1-gate-state.yml`.
- Live lane state on idc02: `~/.local/state/opencode-lane/stage.json` →
  `current_stage: S0`; `lane_gate.py review` → `hold`.
- Quota: repeat the probe after 07:00 +07 (OpenRouter) — expect non-429.

## Next-session runbook (unchanged, in trail doc)

After quota reset + Tony's A: requalify #2 (incident review = S0-provider-outage
review) with runner quiesced → 5× `s0-run` → `review` → promote S0→S1 → staged
`s1-watch.sh` (Tony live ~10 min, records human_minutes) → S1→S2 promote → 5-job
S2 pilot with `independent_devin` verification. **Stop before S3.** Do NOT touch
STRONG_MODELS; S5 is Tony's policy call.

lessons:
- The unmerged-evidence carry chain is now 9 branches deep on local-only dispatch branches; each attempt must `git checkout dispatch/20261127-011421-… -- <explicit file list>` again — nothing reaches master until a sweep merges one of them.
- When carrying forward, exclude the prior attempt's same-day `YYYY-MM-DD-promotion-review` pair — the fresh `lane_gate.py review` output supersedes it and must not be overwritten.
- `lane_gate.py review` is safe to run every attempt: it writes the dated report pair into the worktree AND appends a review entry to `~/.local/state/opencode-lane/stage.json` — that append is expected, not ledger pollution.
- Quota probe is cheap and decisive: one 8-token POST to the pinned model (`or-free-nemotron-ultra`) answers "can the climb run" — 429 = verify-once-then-exit, no need to probe every alias each attempt.
