# Dispatch outcome — 20261127-003933 decision-2026-11-26-tony-run-s

Card: `opencode-lane-regraduation` — DECISION 2026-11-26 Tony: run S1 then S2, hold S5.
Attempt 7 (prior attempts 1–6 all ended blocked or unmerged; prompt's "attempt 2 /
previous run did not merge" = the recurring unmerged-evidence pattern, not a new
code failure).

## Result: BLOCKED — unchanged provider-quota blocker, verified live, evidence secured

No stage change, no requalify, no ledger writes, no model admissions. ~6h to the
OpenRouter free-tier reset (07:00 +07); S1 additionally needs Tony's live watch.

### Verified live state (idc02, ~00:40–00:55 +07)

- Lane `current_stage: S0`; qualification boundary 2026-11-26T15:58:36Z
  (`devin-for-tony`); `jobs_completed {S0: 5}` = attempt-2's banked
  provider-outage fails — metrics.jsonl tail confirms 5× `executor=opencode`
  `shadow_replay` rows `failure_reason=missing_artifact` at 15:59–16:19Z, each
  paired with a passing `executor=l0` row. Any retry climb needs requalify #2
  first (incident review =
  `evals/opencode-lane/reports/2026-11-26-promotion-review-s0-provider-outage.json`).
- Fresh gate evidence this session: `python3 scripts/devnest/lane_gate.py review`
  @2026-11-26T17:47:57Z → `decision=hold`, `verified rate 0.0 < 0.6`, jobs=5,
  verified=0, escalations=5, `human_minutes_total=0`,
  `failure_reasons={missing_artifact:5}` — provider outage, NOT a safety rollback.
  Written to `evals/opencode-lane/reports/2026-11-27-promotion-review.{json,md}`.
- S1 canary staging intact: `~/.local/state/opencode-lane/s1-watch.sh` +
  `staged-jobs/s1-opsread-regrad-20261126.yaml`; committed envelopes
  `s1-nemotron-opsread-idc02.yaml` (master) and `s1-opsread-regrad-20261126.yaml`
  (this branch) both present; `inflight/` empty.

### Quota probe (2026-11-26T17:50Z, 8-token POSTs via litellm proxy) — unchanged + one new data point

- `or-free-nemotron-ultra` / `-nano` / `-35`: all HTTP 429
  `free-models-per-day-high-balance` — OpenRouter account-wide daily cap
  (1000/1000), resets 2026-11-27T00:00Z = **07:00 +07**.
- `agent-local` (qwen2.5:7b): HTTP 200 but **39.4s** for 8 tokens — responsive yet
  slow; still a model-choice change = Tony's call (request option B), and the
  Nov-25 lane ledger shows mostly timeouts/missing_artifact on this alias.
- `gemini-3.1-pro-free`, `or-gemini-2.5-flash`: HTTP 403
  `key_model_access_denied` on the chaba key.
- **`gemini-2.5-flash-lite`: HTTP 200 in 3.9s — NEW.** A responsive model on the
  chaba litellm key outside the exhausted free pools. Whether it is AI-Studio
  free-tier or metered is unverified; switching the qualification model is Tony's
  call either way (option B — and if metered it is also spend).
- Zen free remains inside its ~8.6h retryAfter window (~08:00 +07); gemini
  free-tier daily cap resets ~15:00 +07.

### Board state

- Request `free-lane-providers-quota-capped-until-0-169f8f` still `status: open` —
  Tony has not picked A (wait-for-reset) / B (alternate model) / C (hold).
- `answers.jsonl` carried only the recurring junk `answer — Answer — reply in
  chat` echo from ada (17:39Z). needs-input.txt written with the same question +
  this probe's evidence.

### What changed in the repo (this branch `dispatch/20261127-003933-…`)

- Carried forward **file-identical** all 12 evidence files from local worktree
  `dispatch-wt-20261127-002820` (itself carrying attempts 1–6): 6 dispatch-outcome
  mds, trail doc `docs/ssot/jobs/devnest/2026-11-26-opencode-lane-s1-gate-state.yml`,
  `evals/opencode-lane/jobs/s1-opsread-regrad-20261126.yaml`, and the two
  2026-11-26 promotion-review json/md pairs — because **none of it is on
  origin/master** (verified via `git cat-file`; attempt-4's "210219 merged" note
  was wrong — its outcome md was untracked and its committed files never landed).
- Added fresh `evals/opencode-lane/reports/2026-11-27-promotion-review.{json,md}`
  from this session's `lane_gate.py review`.
- Trail doc: appended `attempt_7_2026_11_27_003933` section (verified state, probe
  matrix, corrected durability note, blocked_on). YAML re-validated.

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
- Attempt-4's trail note claimed dispatch/20261126-210219 "fully merged into origin/master" — it was not; verify merge claims with `git cat-file -e origin/master:<file>`, not branch ancestry.
- The carry-forward chain is now 6 branches deep with zero merges to master; until one dispatch branch merges, EVERY attempt must re-carry all evidence files — check `git ls-remote origin` + `git cat-file` before assuming prior work landed.
- `gemini-2.5-flash-lite` (no -free suffix) answered 200 in 3.9s on the chaba litellm key while every *-free pool was 429 — a possible option-B alternate, but metered-vs-free is unverified and model switch is Tony's call.
- Probing via `litellm-chaba.env` `LITELLM_KEY` works directly against `http://100.102.134.91:4000/v1/chat/completions` with BARE model names — the `litellm/` prefix is an opencode-side namespace, not a proxy model name (returns 403 key_model_access_denied).
