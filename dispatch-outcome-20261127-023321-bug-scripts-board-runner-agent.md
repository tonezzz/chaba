# dispatch-outcome — runner-agent stale-answer resume churn

Card: `runner-agent-stale-answer-resume-churn-a-9f9ffe` (OPS-1473)
Branch: `dispatch/20261127-023321-bug-scripts-board-runner-agent`

## What was wrong

`_job_answer_tick` ORs three answer channels, and ALL THREE could return
a stale answer forever:

1. `_request_answer` matched `requests[]` id `job-input-<cid>` with
   `status==answered` unconditionally, while `_raise_input_request`
   POSTed `/request` with that same stable `request_id` — board-api
   `do_request` raises "duplicate request id" for ANY existing entry,
   so after the first answer the request never re-opened. Every new
   park instantly "resolved" on the old answer.
2. `_last_answer` reads `answers.jsonl` in the finished task's dir —
   and `_job_answer_tick` itself writes the (stale) answer into each
   resumed task's fresh dir, so the next park read it straight back.
3. `_mddb_answer` reads the upserted `answer/<cid>` MDDB doc with no
   time check — a voice answer from park N resolved park N+1, N+2, ...

Observed: 12 identical BLOCKED attempts on `opencode-lane-regraduation`
(2026-11-26 21:00 → 2026-11-27 02:10); the "answer" was an option-echo
("answer — Answer — reply in chat").

## Fix (option b + freshness gates — all in scripts/board/runner-agent.py)

- `_enter_awaiting` stamps `job_awaiting.rid =
  job-input-<cid>-<epoch>` — unique per park — and `_raise_input_request`
  POSTs `/request` with it, so every park gets a fresh OPEN board ask.
  After a successful raise it supersedes still-open `job-input-<cid>*`
  requests from earlier parks via `/respond` "superseded — newer
  needs-input" (answer-sweep maps `superseded` → `none`, no transition),
  keeping exactly one live ask per blocked job.
- `_request_answer(card, cid, rid)` matches only the current park's
  rid; legacy parks without `rid` fall back to the stable
  `job-input-<cid>` id (at most one stale resume per in-flight park,
  then self-heals).
- `_last_answer(ent, since)` and `_mddb_answer(cid, since)` are
  freshness-gated against `job_awaiting.at` via new `_parse_ts` /
  `_answer_is_fresh` (`ANSWER_FRESH_GRACE_S = 300`s cross-host skew
  allowance). MDDB answer time comes from `meta.ts`, then `updatedAt`,
  then the `(<ts>)` in the contentMd header. Unparseable park stamp →
  gate off (legacy); unparseable answer stamp → fail closed.

## Verification

- `tests/board/test_runner_job_lifecycle.py`: 22 passed — incl. new
  `test_second_park_does_not_resume_on_stale_answer` (the card's verify
  criterion, simulated through `finish_pass`: stale carried
  answers.jsonl line + answered old-rid request + no MDDB doc → second
  park holds; answering the CURRENT rid resumes), rid-uniqueness,
  supersede-sweep, and freshness unit tests.
- Runner-agent suite: 81 passed. Full `tests/board`: 257 passed, 1
  unrelated env failure (`test_control_pane_projection` needs the
  gitignored deployed `stacks/web` artifact — absent in worktrees,
  pre-existing).
- Live two-park verification on a real dispatch job was NOT run — a
  live park/resume cycle needs the runner fleet; the finish_pass
  integration test reproduces the exact churn sequence.

## Files

- `scripts/board/runner-agent.py` — the fix (~L2761-2977)
- `tests/board/test_runner_job_lifecycle.py` — 7 new regression tests
- `docs/ssot/jobs/devnest/2026-11-27-runner-agent-stale-answer-resume-churn.yml` — trail doc

## Notes / residual

- The "Answer — reply in chat" option (`action:none`) still marks the
  request answered with an option-echo when clicked — the junk answer
  that fueled this bug. It can no longer auto-churn (each park needs a
  fresh answer), but the option semantics may deserve a board-api/UX
  card.
- Deploy note: runner-agent.py is synced to runner hosts by the normal
  repo-sync path; hosts running stale copies keep the old behavior
  until synced (KNOWN_PITFALLS drift lesson applies — verify sha after
  sync).

lessons:
- "Stale-answer" bugs hide in three channels at once (board request id,
  carried answers.jsonl, upserted MDDB doc) — fixing only the reported
  one leaves the churn alive.
- board-api `do_request` dedupes on request_id for ANY existing entry —
  stable ids can never re-ask; per-incident unique ids (epoch suffix)
  are the re-arm mechanism without a board-api change.
- `_job_answer_tick` writes the consumed answer into the NEXT task
  dir's answers.jsonl — any freshness check must compare against
  `job_awaiting.at`, not just "latest line wins".
- MDDB `answer/<cid>` docs carry `meta.ts` (ISO) + `updatedAt` (epoch)
  — both usable for freshness without parsing contentMd.
