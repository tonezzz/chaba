# Dispatch outcome — 20261127-005450 decision-2026-11-26-tony-run-s

Card: `opencode-lane-regraduation` — DECISION 2026-11-26 Tony: run S1 then S2, hold S5.
Attempt 8 (prior attempts 1–7 all ended blocked or unmerged; prompt's "attempt 2 /
previous run did not merge" = the recurring unmerged-evidence pattern, not a new
code failure).

## Result: BLOCKED — unchanged provider-quota blocker, verified live, evidence secured

No stage change, no requalify, no ledger writes, no model admissions. ~5.9h to the
OpenRouter free-tier reset (07:00 +07); S1 additionally needs Tony's live watch.

### Verified live state (idc02, ~01:00–01:10 +07)

- Lane `current_stage: S0`; qualification boundary 2026-11-26T15:58:36Z
  (`devin-for-tony`); `jobs_completed {S0: 5}` = attempt-2's banked
  provider-outage fails — metrics.jsonl tail unchanged (last rows = the
  16:19Z s0-worktree-safety l0/opencode pair). Any retry climb needs
  requalify #2 first (incident review =
  `evals/opencode-lane/reports/2026-11-26-promotion-review-s0-provider-outage.json`).
- Fresh gate evidence this session: `python3 scripts/devnest/lane_gate.py review`
  @2026-11-26T18:07:27Z → `decision=hold`, `verified rate 0.0 < 0.6`, jobs=5,
  verified=0, escalations=5, `human_minutes_total=0`,
  `failure_reasons={missing_artifact:5}` — provider outage, NOT a safety rollback.
  Written to `evals/opencode-lane/reports/2026-11-27-promotion-review.{json,md}`.
- S1 canary staging intact: `~/.local/state/opencode-lane/s1-watch.sh` +
  `staged-jobs/s1-opsread-regrad-20261126.yaml`; `inflight/` empty.

### Quota probe (2026-11-26T18:06–18:07Z, 8-token POSTs via litellm proxy) — unchanged

- `or-free-nemotron-ultra` / `-nano` / `-35`: all HTTP 429
  `free-models-per-day-high-balance` — OpenRouter account-wide daily cap
  (1000/1000), resets 2026-11-27T00:00Z = **07:00 +07**.
- `agent-local` (qwen2.5:7b): HTTP 200 but **34.7s** for 8 tokens — consistent
  with attempt-7's 39.4s; responsive yet slow/flaky, still a model-choice change
  = Tony's call (request option B), and the Nov-25 lane ledger shows mostly
  timeouts/missing_artifact on this alias.
- `gemini-2.5-flash-lite`: HTTP 200 in **3.0s** — 3rd consecutive responsive
  probe. Whether it is AI-Studio free-tier or metered is unverified; switching
  the qualification model is Tony's call either way (option B — and if metered
  it is also spend).
- Zen free remains inside its ~8.6h retryAfter window (~08:00 +07); gemini
  free-tier daily cap resets ~15:00 +07.

### Board state

- Request `free-lane-providers-quota-capped-until-0-169f8f` still `status: open` —
  Tony has not picked A (wait-for-reset) / B (alternate model) / C (hold).
- `answers.jsonl` carried only the recurring junk `answer — Answer — reply in
  chat` echo from ada (17:54Z). needs-input.txt written with the same question +
  this probe's evidence.

### What changed in the repo (this branch `dispatch/20261127-005450-…`)

- Carried forward **file-identical** all evidence files from local worktree
  `dispatch-wt-20261127-003933` (itself carrying attempts 1–7): 7 dispatch-outcome
  mds, trail doc `docs/ssot/jobs/devnest/2026-11-26-opencode-lane-s1-gate-state.yml`,
  `evals/opencode-lane/jobs/s1-opsread-regrad-20261126.yaml`, and the two
  2026-11-26 promotion-review json/md pairs — because **none of it is on
  origin/master** (verified: this branch forked at 37096381ca whose
  evals/opencode-lane/reports/ ends at 2026-11-12 and docs/ssot/jobs/devnest/
  has no s1-gate-state file).
- Added fresh `evals/opencode-lane/reports/2026-11-27-promotion-review.{json,md}`
  from this session's `lane_gate.py review` (supersedes attempt-7's same-day pair).
- Trail doc: appended `attempt_8_2026_11_27_005450` section. YAML re-validated.

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
- The litellm-chaba.env `LITELLM_URL` already ends in `/v1` — POST to `$LITELLM_URL/chat/completions`, not `/v1/chat/completions` (double-/v1 returns bare 404 `{"detail":"Not Found"}`).
- Broad globs when carrying evidence (`dispatch-outcome-2026112*.md`) sweep in hundreds of already-merged files — harmless (identical content, no diff) but noisy; carry by explicit filename list from `git diff --name-status origin/master...<prior-branch>`.
- `lane_gate.py review` writes its dated `*-promotion-review.{json,md}` into the CALLING checkout's evals/ (REPO-relative) but reads/writes lane state in `~/.local/state/opencode-lane/` — run it from the dispatch worktree so evidence lands on the dispatch branch.
- Attempts 1–7 produced zero merges to master; the carry-forward chain is now 7 branches deep — every attempt must re-verify `git cat-file -e origin/master:<file>` before assuming prior evidence landed.
