# Dispatch outcome — 20261127-000355 decision-2026-11-26-tony-run-s

Card: `opencode-lane-regraduation` — DECISION 2026-11-26 Tony: run S1 then S2, hold S5.
Attempt 4 (prior attempts: 210219 merged, 224727 unmerged, 234836 unmerged-at-start).

## Result: BLOCKED — unchanged provider-quota blocker, evidence secured

No stage change, no requalify, no ledger writes, no model admissions.

### Verified live state (idc02, ~00:05–00:15 +07)

- Lane `current_stage: S0`; qualification boundary 2026-11-26T15:58:36Z (`devin-for-tony`);
  `jobs_completed {S0: 5}` = attempt-2's banked provider-outage fails; last review
  2026-11-26T16:24:26Z decision=`hold` (0/5 verified, zero safety-critical → HOLD not rollback).
- Any retry climb needs requalify #2 first (incident review =
  `evals/opencode-lane/reports/2026-11-26-promotion-review-s0-provider-outage.json`).
- `runner-agent.timer` active; `~/.local/bin/runner-agent` sha256-identical to exec-checkout
  `scripts/board/runner-agent.py`; `inflight/` empty.
- S1 canary staging intact: `~/.local/state/opencode-lane/s1-watch.sh` +
  `staged-jobs/s1-opsread-regrad-20261126.yaml`, byte-identical to committed
  `evals/opencode-lane/jobs/s1-opsread-regrad-20261126.yaml`.

### Quota probe (2026-11-26T17:08Z, 1-token POSTs via litellm proxy)

- `or-free-nemotron-ultra` / `-35` / `-nano`: all HTTP 429
  `free-models-per-day-high-balance`, `X-RateLimit-Remaining: 0`,
  `X-RateLimit-Reset: 1795737600000` = **2026-11-27T00:00:00Z = 07:00 +07**.
- `agent-local`: curl timed out at 30s (unresponsive; switching models is Tony's call anyway).
- Zen free still inside its ~8.6h retryAfter window (~08:00 +07 per attempt-2 measurement).

### Board state

- Request `free-lane-providers-quota-capped-until-0-169f8f` still `status: open` —
  Tony has not picked A (wait-for-reset) / B (alternate non-free model) / C (hold).
- `answers.jsonl` carried only the junk `answer — Answer — reply in chat` echo from ada.
- needs-input.txt written with the same question + probe evidence.

### What changed in the repo (this branch `dispatch/20261127-000355-…`)

- Carried forward **file-identical** all 9 evidence files from still-unmerged attempt-3
  branch `dispatch/20261126-234836` (3 dispatch-outcome mds, trail doc,
  `evals/opencode-lane/jobs/s1-opsread-regrad-20261126.yaml`, and the two
  2026-11-26 promotion-review json/md pairs) so the trail reaches master with THIS
  dispatch's merge regardless of sweep order. Attempt-1 branch verified already merged.
- `docs/ssot/jobs/devnest/2026-11-26-opencode-lane-s1-gate-state.yml`: appended
  `attempt_4_2026_11_27_000355` section (verified state, probe results, durability fix,
  blocked_on, cadence note).

## How to verify

- `git show --stat HEAD` on this branch; files under `evals/opencode-lane/reports/2026-11-26-*`
  and `docs/ssot/jobs/devnest/2026-11-26-opencode-lane-s1-gate-state.yml`.
- Live lane state: `python3 -c "import json;print(json.load(open('$HOME/.local/state/opencode-lane/stage.json'))['current_stage'])"` on idc02 → `S0`.
- Quota: repeat the 1-token probe after 07:00 +07 — expect non-429.

## Next-session runbook (unchanged, now in trail doc)

After quota reset + Tony's A: requalify #2 (incident review = S0-provider-outage review)
with runner quiesced → 5× `s0-run` → `review` → promote S0→S1 → staged `s1-watch.sh`
(Tony live ~10 min, records human_minutes) → S1→S2 promote → 5-job S2 pilot with
`independent_devin` verification. **Stop before S3.** Do NOT touch STRONG_MODELS; S5 is
Tony's policy call.

lessons:
- OpenRouter free-tier quota is account-wide per UTC day — probe `X-RateLimit-Reset` once, then stop re-dispatching verification attempts until reset; every pre-reset attempt only re-confirms the same 429.
- Unmerged dispatch branches lose evidence if a later attempt doesn't carry it forward — checkout evidence files file-identical onto the newest dispatch branch so whichever merges last wins cleanly.
- `answers.jsonl`/`kind:"answer"` lines can carry junk UI echoes ("answer — Answer — reply in chat"); treat only substantive text as an answer and keep the board request open.
- The card's `awaiting_action: true` does not stop the dispatcher from re-firing the same spec every ~30–90 min — write needs-input.txt early and make each attempt cheap (verify-once-then-exit).
- `litellm/agent-local` alias timed out (30s+) when probed directly — it is not a quick fallback for quota-blocked free models, and model choice for qualification is a Tony decision anyway.
