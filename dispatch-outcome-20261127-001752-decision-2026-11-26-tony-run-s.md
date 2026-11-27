# Dispatch outcome — 20261127-001752 decision-2026-11-26-tony-run-s

Card: `opencode-lane-regraduation` — DECISION 2026-11-26 Tony: run S1 then S2, hold S5.
Attempt 5 (prior attempts: 210219 merged, 224727/234836/000355 unmerged-at-start).

## Result: BLOCKED — unchanged provider-quota blocker, new probe evidence + trail secured

No stage change, no requalify, no ledger writes, no model admissions.

### Verified live state (idc02, ~00:18–00:30 +07)

- Lane `current_stage: S0`; qualification boundary 2026-11-26T15:58:36Z (`devin-for-tony`);
  `jobs_completed {S0: 5}` = attempt-2's banked provider-outage fails; last review
  2026-11-26T16:24:26Z decision=`hold` (0/5 verified, zero safety-critical → HOLD not rollback).
- Any retry climb needs requalify #2 first (incident review =
  `evals/opencode-lane/reports/2026-11-26-promotion-review-s0-provider-outage.json`).
- S1 canary staging intact: `~/.local/state/opencode-lane/s1-watch.sh` +
  `staged-jobs/s1-opsread-regrad-20261126.yaml`; `inflight/` empty.

### Quota probe (2026-11-26T17:25Z, 1-token POSTs via litellm proxy) — NEW findings

- `or-free-nemotron-ultra` / `-35` / `-nano`: all HTTP 429
  `free-models-per-day-high-balance`, `X-RateLimit-Reset: 1795737600000` =
  **2026-11-27T00:00:00Z = 07:00 +07** (unchanged).
- `gemini-3.5-flash-lite-free` / `gemini-3.5-flash-free`: HTTP 429 — **AI Studio
  free-tier DAILY cap (500/day) also exhausted**, retryDelay 52612s ≈ 14.6h →
  ~15:00 +07. New this attempt: the gemini free pool is capped too.
- `agent-local` (ollama_chat/qwen2.5:7b-instruct): **HTTP 200 in 5.8s — responsive
  this probe** (attempts 3/4 saw 30s timeouts; the alias is intermittent).
- `or-free-north-code`, `gemini-2.5-flash-lite-free`, `cf-nemotron-120b`:
  HTTP 400 invalid model name on `/chat/completions` (API-surface mismatch, not quota).
- Zen free still inside its ~8.6h retryAfter window (~08:00 +07).

**Every remote free pool is now daily-capped.** The only live $0 lane candidate is
`agent-local`, but (a) switching the qualification model is Tony's call — it falls
under open request option B — and (b) it is historically flaky in this lane: the
Nov-25 ledger shows mostly ~420s timeouts / missing_artifact with occasional
verifier passes. A climb on qwen2.5:7b-instruct may fail on capability and bank
more rows forcing yet another requalify.

### Board state

- Request `free-lane-providers-quota-capped-until-0-169f8f` still `status: open` —
  Tony has not picked A (wait-for-reset) / B (alternate model) / C (hold).
- `answers.jsonl` carried only the recurring junk `answer — Answer — reply in chat`
  echo from ada (17:19Z). needs-input.txt written with the same question + probe
  evidence including the new agent-local/gemini-free findings.

### What changed in the repo (this branch `dispatch/20261127-001752-…`)

- Carried forward **file-identical** all 10 evidence files from still-unmerged
  attempt-4 branch `dispatch/20261127-000355` (4 dispatch-outcome mds incl.
  attempts 1–4, trail doc, `evals/opencode-lane/jobs/s1-opsread-regrad-20261126.yaml`,
  and the two 2026-11-26 promotion-review json/md pairs) so the trail reaches master
  with THIS dispatch's merge regardless of sweep order.
- `docs/ssot/jobs/devnest/2026-11-26-opencode-lane-s1-gate-state.yml`: appended
  `attempt_5_2026_11_27_001752` section (verified state, full probe matrix,
  agent-local caveat, durability fix, blocked_on).

## How to verify

- `git show --stat HEAD` on this branch; files under `evals/opencode-lane/reports/2026-11-26-*`
  and `docs/ssot/jobs/devnest/2026-11-26-opencode-lane-s1-gate-state.yml`.
- Live lane state on idc02: `stage.json` → `current_stage: S0`.
- Quota: repeat the 1-token probe after 07:00 +07 (OpenRouter) — expect non-429.

## Next-session runbook (unchanged, now in trail doc)

After quota reset + Tony's A: requalify #2 (incident review = S0-provider-outage
review) with runner quiesced → 5× `s0-run` → `review` → promote S0→S1 → staged
`s1-watch.sh` (Tony live ~10 min, records human_minutes) → S1→S2 promote → 5-job
S2 pilot with `independent_devin` verification. **Stop before S3.** Do NOT touch
STRONG_MODELS; S5 is Tony's policy call.

lessons:
- ALL remote free pools are now daily-capped, not just OpenRouter: AI Studio gemini free tier (500/day) was also exhausted at 00:25 +07 with ~14.6h retry — probe every candidate pool before declaring "only OpenRouter capped".
- `litellm/agent-local` is intermittent, not dead: timed out at 30s in attempts 3/4 but returned HTTP 200 in 5.8s on attempt 5 — a single timeout probe is not proof of unavailability, but its Nov-25 lane ledger is mostly timeouts so it remains a risky qualification model regardless.
- Some litellm model-list entries (or-free-north-code, gemini-2.5-flash-lite-free, cf-nemotron-120b) 400 on /chat/completions — they are listed but not chat-completions-routable; don't count them as quota evidence either way.
- Unmerged dispatch branches still lose evidence if a later attempt doesn't carry it forward — attempt-4's branch was again unmerged at session start; file-identical checkout onto the newest branch remains the correct durability pattern (now 4 branches deep).
- The dispatcher keeps re-firing this card ~every 30–90 min through the quota window; verify-once-then-exit with a fresh probe timestamp is the cheapest correct behavior — do NOT burn climb attempts against capped providers.
