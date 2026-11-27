# Dispatch outcome — 20261127-002820 decision-2026-11-26-tony-run-s

Card: `opencode-lane-regraduation` — DECISION 2026-11-26 Tony: run S1 then S2, hold S5.
Attempt 6 (prior: 210219 merged; 224727/234836/000355/001752 unmerged-at-start).

## Result: BLOCKED — unchanged provider-quota blocker, verified live, evidence secured

No stage change, no requalify, no ledger writes, no model admissions. ~6.5h to the
OpenRouter free-tier reset (07:00 +07); S1 additionally needs Tony's live watch.

### Verified live state (idc02, ~00:29–00:32 +07)

- Lane `current_stage: S0`; qualification boundary 2026-11-26T15:58:36Z
  (`devin-for-tony`); `jobs_completed {S0: 5}` = attempt-2's banked
  provider-outage fails (`missing_artifact` rows at 15:59–16:19Z); last review
  2026-11-26T16:24:26Z decision=`hold` (0/5 verified, zero safety flags → HOLD,
  not rollback). Any retry climb needs requalify #2 first (incident review =
  `evals/opencode-lane/reports/2026-11-26-promotion-review-s0-provider-outage.json`).
- S1 canary staging intact: `~/.local/state/opencode-lane/s1-watch.sh` (966B exec)
  + `staged-jobs/s1-opsread-regrad-20261126.yaml`; `inflight/` empty.
- runner-agent.timer active on idc02 (last tick 00:28:36 +07); no drift alert.

### Quota probe (2026-11-26T17:30Z, 1-token POSTs via litellm proxy) — unchanged

- `or-free-nemotron-ultra` / `-35` / `-nano`: all HTTP 429
  `free-models-per-day-high-balance`, `X-RateLimit-Reset: 1795737600000` =
  **2026-11-27T00:00:00Z = 07:00 +07** (account-wide daily cap, 1000/1000 used).
- `gemini-3.5-flash-lite-free`: HTTP 429 AI Studio free-tier daily cap (~15:00 +07).
- `agent-local` (ollama_chat/qwen2.5:7b-instruct): HTTP 200 but **31.6s wall** for
  4 tokens — slower than attempt-5's 5.8s; intermittent/slow confirmed. Still not a
  qualified substitute: switching the qualification model is Tony's call
  (request option B) and the Nov-25 lane ledger shows mostly timeouts /
  missing_artifact on this alias.
- Zen free remains inside its ~8.6h retryAfter window (~08:00 +07).

### Board state

- Request `free-lane-providers-quota-capped-until-0-169f8f` still `status: open` —
  Tony has not picked A (wait-for-reset) / B (alternate model) / C (hold).
- `answers.jsonl` carried only the recurring junk `answer — Answer — reply in
  chat` echo from ada (17:28Z). needs-input.txt written with the same question +
  this probe's evidence.

### What changed in the repo (this branch `dispatch/20261127-002820-…`)

- Carried forward **file-identical** all 11 evidence files from still-unmerged
  attempt-5 branch `dispatch/20261127-001752` (5 dispatch-outcome mds incl.
  attempts 1–5, trail doc, `evals/opencode-lane/jobs/s1-opsread-regrad-20261126.yaml`,
  and the two 2026-11-26 promotion-review json/md pairs) so the trail reaches
  master with THIS dispatch's merge regardless of sweep order.
- `docs/ssot/jobs/devnest/2026-11-26-opencode-lane-s1-gate-state.yml`: appended
  `attempt_6_2026_11_27_002820` section (verified state, probe matrix,
  durability fix, blocked_on). YAML re-validated.

## How to verify

- `git show --stat HEAD` on this branch; files under `evals/opencode-lane/reports/2026-11-26-*`
  and `docs/ssot/jobs/devnest/2026-11-26-opencode-lane-s1-gate-state.yml`.
- Live lane state on idc02: `~/.local/state/opencode-lane/stage.json` →
  `current_stage: S0`.
- Quota: repeat the 1-token probe after 07:00 +07 (OpenRouter) — expect non-429.

## Next-session runbook (unchanged, in trail doc)

After quota reset + Tony's A: requalify #2 (incident review = S0-provider-outage
review) with runner quiesced → 5× `s0-run` → `review` → promote S0→S1 → staged
`s1-watch.sh` (Tony live ~10 min, records human_minutes) → S1→S2 promote → 5-job
S2 pilot with `independent_devin` verification. **Stop before S3.** Do NOT touch
STRONG_MODELS; S5 is Tony's policy call.

lessons:
- The dispatcher re-fired this card ~1 minute after attempt 5 exited — expect back-to-back attempts through the quota window; a fast verify-and-exit (~4 min) is the right cost profile, not a reason to skip the live probe.
- `agent-local` (qwen2.5:7b) returned 200 but took 31.6s for 4 tokens this probe vs 5.8s last attempt — latency variance is as disqualifying as outright timeouts for a qualification model; do not treat a single fast probe as "recovered".
- All four prior attempt branches remained unmerged at session start; the carry-forward-via-file-identical-checkout pattern is now 5 branches deep and still the only durability mechanism until one merges.
