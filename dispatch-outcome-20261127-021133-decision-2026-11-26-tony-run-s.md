# Dispatch outcome — 20261127-021133 decision-2026-11-26-tony-run-s

Card: `opencode-lane-regraduation` — DECISION 2026-11-26 Tony: run S1 then S2, hold S5.
Attempt 13 (attempts 1–12 all ended blocked on the same provider-quota wall or
unmerged; the prompt's "attempt 2 / previous run did not merge" = the recurring
unmerged-evidence pattern, not a new code failure).

## Result: BLOCKED — unchanged provider-quota blocker, verified live; churn loop diagnosed and held

No stage change, no requalify, no ledger writes, no model admissions. ~4.7h to
the OpenRouter free-tier reset (07:00 +07); S1 additionally needs Tony's live
watch regardless of quota.

### Verified live state (idc02, ~02:12–02:20 +07)

- Lane `current_stage: S0`; qualification boundary 2026-11-26T15:58:36Z
  (`devin-for-tony`, OPS-1363 epoch-pollution adjudication); `jobs_completed
  {S0: 5}` = attempt-2's banked provider-outage fails — any retry climb needs
  requalify #2 first (incident review =
  `evals/opencode-lane/reports/2026-11-26-promotion-review-s0-provider-outage.json`).
- Fresh gate evidence this session: `python3 scripts/devnest/lane_gate.py review`
  @19:19:16Z → `decision=hold`, `verified rate 0.0 < 0.6`, jobs=5, verified=0,
  escalations=5, `human_minutes_total=0`,
  `failure_reasons={missing_artifact:5}` — provider outage, NOT a safety
  rollback. Written to `evals/opencode-lane/reports/2026-11-27-promotion-review.{json,md}`.
- S1 canary staging intact: `~/.local/state/opencode-lane/s1-watch.sh` +
  `staged-jobs/s1-opsread-regrad-20261126.yaml`; `inflight/` empty.
  runner-agent.timer active.

### Quota probe (2026-11-26T19:13–19:15Z, 8-token POSTs via litellm proxy) — unchanged wall

- `or-free-nemotron-ultra` (the pinned qualification/S1 model): HTTP 429
  `free-models-per-day-high-balance` — OpenRouter account-wide daily cap,
  `X-RateLimit-Reset=1795737600000` = 2026-11-27T00:00Z = **07:00 +07**.
- `gemini-2.5-flash-lite`: HTTP 200 in **3.4s** — 8th consecutive responsive
  probe; `provider=Google AI Studio`, metered cost $0.0000012 on 9 tokens —
  responsive AND paid, so option B is spend + qualification-model change:
  Tony's call either way.
- `agent-local` (ollama qwen2.5:7b): HTTP 200 in **34.7s** — responsive but
  slow; historically flaky in-lane. Still Tony's call.
- Zen free remains inside its ~8.6h retryAfter window (~08:00 +07); gemini
  `*-free` pools capped until ~15:00 +07 per attempt-5.

### NEW: churn-loop root cause found + card held (first deviation from prior attempts)

The ~20-minute re-dispatch cadence is a **mechanism bug**, not scheduler noise:

- `runner-agent.finish_pass` parks a needs-input-blocked task via
  `_enter_awaiting`, then `_job_answer_tick` resumes it when any of three
  answer channels yields text.
- `_request_answer()` (runner-agent.py ~L2780) returns the answer of card
  request `job-input-<cid>` whenever `status=='answered'` — that request was
  answered **once** (2026-11-26, generic `answer — reply in chat` option echo)
  and stays `answered` forever; `_raise_input_request` dedupes on the same
  `request_id`, so it is never re-opened for the new question.
- Result: every park instantly "answers" with the stale echo → `start_task`
  resume → same quota wall → needs-input → park → stale answer. **12 attempts
  burned this way.**
- The designed escape exists but was never taken: the job-input request's
  `hold` option (`action=hold` → `do_action` hold → `action.status=idle`), or a
  direct `POST /action do=hold`. Once `status != "running"`, the next
  finish_pass releases the local claim ("A human moved the card on — release")
  and the card stops being claimable until Tony answers/queues it.

**Action taken this attempt:** wrote `needs-input.txt` (same unblock question)
AND `POST /action do=hold` on the card — breaking the loop with the designed
hold path instead of adding a 13th identical verify-only pass. When Tony
answers request `free-lane-providers-quota-capped-until-0-169f8f` (or queues
retries), a fresh dispatch picks up the real answer. Card bug for the
stale-answer resume defect filed via board-api (see card comms).

### Board state

- Request `free-lane-providers-quota-capped-until-0-169f8f` still `status: open` —
  Tony has not picked A (wait-for-reset) / B (alternate model) / C (hold).
- `answers.jsonl` carried only the recurring junk `answer — Answer — reply in
  chat` echo from ada (19:11Z) — the same stale-answer artifact described above.

### What changed in the repo (this branch `dispatch/20261127-021133-…`)

- Carried forward **file-identical** all evidence files from local branch
  `dispatch/20261127-015902-decision-2026-11-26-tony-run-s` (itself carrying
  attempts 1–12): 12 dispatch-outcome mds,
  `docs/ssot/jobs/devnest/2026-11-26-opencode-lane-s1-gate-state.yml`,
  `evals/opencode-lane/jobs/s1-opsread-regrad-20261126.yaml`, and the
  2026-11-26 promotion-review pairs (rollback + s0-provider-outage) — because
  **none of it is on origin/master**.
- Deliberately NOT carried: attempt-12's `2026-11-27-promotion-review.{json,md}`
  (this session's fresh pair supersedes) and
  `reports/SSOT_OPTIMIZATION_WARNINGS.json` (already on master).
- Added fresh `evals/opencode-lane/reports/2026-11-27-promotion-review.{json,md}`
  from this session's `lane_gate.py review`.
- Trail doc: appended `attempt_13_2026_11_27_021133` section (incl. churn-loop
  root cause + hold action).

## How to verify

- `git show --stat HEAD` on this branch; files under `evals/opencode-lane/reports/2026-11-26-*`
  and `2026-11-27-*`, `evals/opencode-lane/jobs/s1-opsread-regrad-20261126.yaml`,
  `docs/ssot/jobs/devnest/2026-11-26-opencode-lane-s1-gate-state.yml`.
- Live lane state on idc02: `~/.local/state/opencode-lane/stage.json` →
  `current_stage: S0`; `lane_gate.py review` → `hold`.
- Card state: `GET /cards` → `opencode-lane-regraduation` should show
  `column: backlog`, `action.status: idle` after the hold lands + session end.
- Quota: repeat the probe after 07:00 +07 (OpenRouter) — expect non-429.

## Next-session runbook (unchanged, in trail doc)

After quota reset + Tony's A: requalify #2 (incident review = S0-provider-outage
review) with runner quiesced → 5× `s0-run` → `review` → promote S0→S1 → staged
`s1-watch.sh` (Tony live ~10 min, records human_minutes) → S1→S2 promote → 5-job
S2 pilot with `independent_devin` verification. **Stop before S3.** Do NOT touch
STRONG_MODELS; S5 is Tony's policy call.

lessons:
- runner-agent `_request_answer()` returns ANY answered `job-input-<cid>` request forever — a stale generic option echo auto-resumes every needs-input park into the same wall; check `scripts/board/runner-agent.py` L2780/L2850 before assuming a blocked card will stay parked.
- The designed escape from that loop is `/action do=hold` (or the job-input request's `hold` option): status→idle makes the next finish_pass release the claim; the card re-arms only when Tony answers/queues.
- The unmerged-evidence carry chain is now 12 branches deep on local-only dispatch branches; each attempt must `git checkout dispatch/20261127-015902-… -- <explicit file list>` — nothing reaches master until a sweep merges one of them.
- When carrying forward, exclude the prior attempt's same-day `YYYY-MM-DD-promotion-review` pair — the fresh `lane_gate.py review` output supersedes it and must not be overwritten.
- `lane_gate.py review` is safe to run every attempt: it writes the dated report pair into the worktree AND appends a review entry to `~/.local/state/opencode-lane/stage.json` — that append is expected, not ledger pollution.
