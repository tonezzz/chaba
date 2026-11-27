# Dispatch outcome — 20261127-011421 decision-2026-11-26-tony-run-s

Card: `opencode-lane-regraduation` — DECISION 2026-11-26 Tony: run S1 then S2, hold S5.
Attempt 9 (prior attempts 1–8 all ended blocked or unmerged; prompt's "attempt 2 /
previous run did not merge" = the recurring unmerged-evidence pattern, not a new
code failure).

## Result: BLOCKED — unchanged provider-quota blocker, verified live, evidence secured

No stage change, no requalify, no ledger writes, no model admissions. ~5.7h to the
OpenRouter free-tier reset (07:00 +07); S1 additionally needs Tony's live watch.

### Verified live state (idc02, ~01:15–01:22 +07)

- Lane `current_stage: S0`; qualification boundary 2026-11-26T15:58:36Z
  (`devin-for-tony`); `jobs_completed {S0: 5}` = attempt-2's banked
  provider-outage fails — metrics.jsonl tail unchanged (last rows still the
  16:19Z s0-worktree-safety pair). Any retry climb needs requalify #2 first
  (incident review =
  `evals/opencode-lane/reports/2026-11-26-promotion-review-s0-provider-outage.json`).
- Fresh gate evidence this session: `python3 scripts/devnest/lane_gate.py review`
  @2026-11-26T18:21:38Z → `decision=hold`, `verified rate 0.0 < 0.6`, jobs=5,
  verified=0, escalations=5, `human_minutes_total=0`,
  `failure_reasons={missing_artifact:5}` — provider outage, NOT a safety rollback.
  Written to `evals/opencode-lane/reports/2026-11-27-promotion-review.{json,md}`.
- S1 canary staging intact: `~/.local/state/opencode-lane/s1-watch.sh` (966B exec,
  mtime Nov-26 23:02) + `staged-jobs/s1-opsread-regrad-20261126.yaml`;
  `inflight/` empty. runner-agent.timer active (last run status=0/SUCCESS).

### Quota probe (2026-11-26T18:16–18:19Z, 8-token POSTs via litellm proxy) — unchanged wall, wider coverage

- `GET /v1/models`: 47 models listed.
- `or-free-nemotron-ultra` (the S1 envelope's pinned model): HTTP 429
  `free-models-per-day-high-balance` — OpenRouter account-wide daily cap,
  resets 2026-11-27T00:00Z = **07:00 +07**.
- `gemini-2.5-flash-lite-free` / `gemini-2.5-flash-free`: HTTP 400 invalid model
  name — routes not configured on this proxy.
- `gemini-3.5-flash-lite-free` / `gemini-3.5-flash-free`: HTTP 429 geminiException
  — AI Studio daily cap, same wall (~15:00 +07 reset per attempt-5).
- `gemini-2.5-flash-lite`: HTTP 200 in **3.3s** — 4th consecutive responsive probe.
  Whether it is AI-Studio free-tier or metered is unverified; switching the
  qualification model is Tony's call either way (request option B — and if
  metered it is also spend).
- `agent-local` (qwen2.5:7b): HTTP 200 in **24.3s** for 8 tokens — responsive but
  slow; historically flaky in-lane (timeouts, shared-checkout scope_violation
  false positives). Still Tony's call.
- Zen free remains inside its ~8.6h retryAfter window (~08:00 +07).

### Board state

- Request `free-lane-providers-quota-capped-until-0-169f8f` still `status: open` —
  Tony has not picked A (wait-for-reset) / B (alternate model) / C (hold).
- `answers.jsonl` carried only the recurring junk `answer — Answer — reply in
  chat` echo from ada (18:14Z). needs-input.txt written with the same question +
  this probe's evidence.

### What changed in the repo (this branch `dispatch/20261127-011421-…`)

- Carried forward **file-identical** all evidence files from local branch
  `dispatch/20261127-005450-decision-2026-11-26-tony-run-s` (itself carrying
  attempts 1–8): 8 dispatch-outcome mds,
  `docs/ssot/jobs/devnest/2026-11-26-opencode-lane-s1-gate-state.yml`,
  `evals/opencode-lane/jobs/s1-opsread-regrad-20261126.yaml`, and the
  2026-11-26/2026-11-27 promotion-review json/md pairs — because **none of it is
  on origin/master** (this branch forked at 5a317cbafb whose
  evals/opencode-lane/reports/ ends at 2026-11-12).
- Added fresh `evals/opencode-lane/reports/2026-11-27-promotion-review.{json,md}`
  from this session's `lane_gate.py review` (supersedes attempt-8's same-day pair).
- Trail doc: appended `attempt_9_2026_11_27_011421` section.

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
- Every remote free pool is now confirmed capped, not just OpenRouter: gemini-3.5-flash-lite-free/-flash-free return the same 429 daily-cap, and the 2.5-flash-lite/-flash `-free` aliases are not even routed (400 invalid model name) — don't re-probe them as "maybe free".
- `gemini-2.5-flash-lite` (no -free suffix) answered 200 four probes running but metered-vs-free is still unverified — treat any non-`-free` litellm alias as potential spend until the proxy config proves otherwise.
- The unmerged-evidence carry chain is now 8 branches deep on local-only dispatch branches; each attempt must `git checkout <prior-branch> -- <explicit file list>` again — nothing reaches master until a sweep merges one of them.
- `lane_gate.py review` run from the dispatch worktree both writes the dated promotion-review pair into the branch AND appends a review entry to `~/.local/state/opencode-lane/stage.json` — safe to run every attempt for fresh gate evidence.
