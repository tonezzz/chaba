# Dispatch outcome — 20261127-015902 decision-2026-11-26-tony-run-s

Card: `opencode-lane-regraduation` — DECISION 2026-11-26 Tony: run S1 then S2, hold S5.
Attempt 12 (attempts 1–11 all ended blocked on the same provider-quota wall or
unmerged; the prompt's "attempt 2 / previous run did not merge" = the recurring
unmerged-evidence pattern, not a new code failure).

## Result: BLOCKED — unchanged provider-quota blocker, verified live, evidence secured

No stage change, no requalify, no ledger writes, no model admissions. ~5.0h to
the OpenRouter free-tier reset (07:00 +07); S1 additionally needs Tony's live
watch regardless of quota.

### Verified live state (idc02, ~01:59–02:03 +07)

- Lane `current_stage: S0`; qualification boundary 2026-11-26T15:58:36Z
  (`devin-for-tony`, OPS-1363 epoch-pollution adjudication); `jobs_completed
  {S0: 5}` = attempt-2's banked provider-outage fails — any retry climb needs
  requalify #2 first (incident review =
  `evals/opencode-lane/reports/2026-11-26-promotion-review-s0-provider-outage.json`).
- Fresh gate evidence this session: `python3 scripts/devnest/lane_gate.py review`
  @19:03:21Z → `decision=hold`, `verified rate 0.0 < 0.6`, jobs=5, verified=0,
  escalations=5, `human_minutes_total=0`,
  `failure_reasons={missing_artifact:5}` — provider outage, NOT a safety
  rollback. Written to `evals/opencode-lane/reports/2026-11-27-promotion-review.{json,md}`.
- S1 canary staging intact: `~/.local/state/opencode-lane/s1-watch.sh` +
  `staged-jobs/s1-opsread-regrad-20261126.yaml`; `inflight/` empty.
  runner-agent.timer active (user unit; last tick 02:00:18 +07).

### Quota probe (2026-11-26T19:02–19:03Z, 8-token POSTs via litellm proxy) — unchanged wall

- `or-free-nemotron-ultra` (the pinned qualification/S1 model): HTTP 429
  `free-models-per-day-high-balance` — OpenRouter account-wide daily cap,
  `X-RateLimit-Reset=1795737600000` = 2026-11-27T00:00Z = **07:00 +07**.
- `gemini-2.5-flash-lite`: HTTP 200 in **3.5s** — 7th consecutive responsive
  probe. Upstream `google/gemini-2.5-flash-lite` (AI Studio direct, NOT
  OpenRouter) per attempt-11's `/model/info` — outside the OpenRouter daily
  cap. Billing tier still unverifiable from litellm; switching the
  qualification model is Tony's call either way (request option B).
- `agent-local` (ollama qwen2.5:7b): HTTP 200 in **36.1s** — responsive but
  slow; historically flaky in-lane. Still Tony's call.
- Zen free remains inside its ~8.6h retryAfter window (~08:00 +07); gemini
  `*-free` pools capped until ~15:00 +07 per attempt-5.

### Board state

- Request `free-lane-providers-quota-capped-until-0-169f8f` still `status: open` —
  Tony has not picked A (wait-for-reset) / B (alternate model) / C (hold).
- `answers.jsonl` carried only the recurring junk `answer — Answer — reply in
  chat` echo from ada (18:59Z). needs-input.txt written with the same question +
  this probe's evidence.

### What changed in the repo (this branch `dispatch/20261127-015902-…`)

- Carried forward **file-identical** all evidence files from local branch
  `dispatch/20261127-014448-decision-2026-11-26-tony-run-s` (itself carrying
  attempts 1–11): 11 dispatch-outcome mds,
  `docs/ssot/jobs/devnest/2026-11-26-opencode-lane-s1-gate-state.yml`,
  `evals/opencode-lane/jobs/s1-opsread-regrad-20261126.yaml`, and the
  2026-11-26 promotion-review pairs (rollback + s0-provider-outage) — because
  **none of it is on origin/master**.
- Deliberately NOT carried: attempt-11's `2026-11-27-promotion-review.{json,md}`
  (this session's fresh pair supersedes) and card/render-state churn files.
- Added fresh `evals/opencode-lane/reports/2026-11-27-promotion-review.{json,md}`
  from this session's `lane_gate.py review`.
- Trail doc: appended `attempt_12_2026_11_27_015902` section.

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
- The unmerged-evidence carry chain is now 11 branches deep on local-only dispatch branches; each attempt must `git checkout dispatch/20261127-014448-… -- <explicit file list>` again — nothing reaches master until a sweep merges one of them.
- When carrying forward, exclude the prior attempt's same-day `YYYY-MM-DD-promotion-review` pair — the fresh `lane_gate.py review` output supersedes it and must not be overwritten.
- `lane_gate.py review` is safe to run every attempt: it writes the dated report pair into the worktree AND appends a review entry to `~/.local/state/opencode-lane/stage.json` — that append is expected, not ledger pollution.
- Quota probe is cheap and decisive: one 8-token POST to the pinned model (`or-free-nemotron-ultra`) answers "can the climb run" — 429 = verify-once-then-exit; secondary probes (gemini-2.5-flash-lite, agent-local) only matter if Tony picks option B.
- At ~02:00 +07 with reset at 07:00 +07, re-dispatch cadence guarantees repeated identical BLOCKED outcomes; the binding constraint is Tony's A/B/C answer + live-watch availability, not anything an agent can change.
