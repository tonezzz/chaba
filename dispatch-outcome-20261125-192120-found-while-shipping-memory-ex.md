# Dispatch outcome — ada-session-summary-inflow-stalled (attempt 2)

## What I found

Attempt 1 (tony-dell, ~15:14) found the root cause but produced no commits, so
nothing landed. This attempt re-verified the RCA independently and committed
the evidence trail.

**Root cause (confirmed live 2026-11-25 ~19:30+07):** `memory-distill.timer`
on idc03 is healthy — it reads the correct source
(`ada-ha-recall-summary-<instance>`, `kind=session-summary`). The writer is
the dead part: session-summary docs are produced only by ada-voice
`ConversationMemory.persist()` → `_update_summary()` →
`_save_session_summary()`, and `persist()` is invoked at session close ONLY by
`GeminiLiveProvider.close()` (`realtime_provider.py:6712`).
`OpenRouterTextProvider.close()` (`openrouter_provider.py:638` on
`origin/main`) never calls it — verified via `git show origin/main:...`.
Text-mode routing (`?mode=text` in line/tg relays, `ADA_TEXT_ONLY_CALLERS`,
`ADA_TEXT_ONLY_CHANNELS` default telegram/tg/line + chat/web on ada-ha-tony)
silently moved every lane off Gemini Live at different times → last summary
docs: tony 10-03, dev 10-09, kk 10-13, kk-dev 10-14, michael 10-17.

**Fresh MDDB evidence (this session):** `kind=session-summary` +
`meta.date >= 2026-10-15` → tony=0 (newest ~10-03), michael=28 docs all
10-16/17, kk/kk-dev/dev/shared=0. Stall is live.

**memory-distill verdict:** no change needed — victim, not the bug. It resumes
automatically once the writer is fixed (incremental state only tracks seen
keys).

**Critical finding — the fix is stranded:** ada-voice
`dispatch/text-mode-session-persist` commit `c14758b` exists ONLY as a local
branch on tony-macbook (`~/CascadeProjects/ada-voice-wt-text-mode-persist`),
1 ahead / 7 behind `origin/main`, never pushed (`git ls-remote` confirms).
`origin/main` still has the bug. Card
`ada-voice-text-mode-sessions-never-call-e007bd` shows done/verified — it
auto-closed on the *chaba* dispatch-branch merge while the ada-voice artifact
never landed. If that worktree is GC'd the fix is lost.

## What changed (committed on dispatch/20261125-192120-found-while-shipping-memory-ex)

- `docs/ssot/jobs/ada/2026-11-25-session-summary-inflow-stalled.yml` — full
  RCA + evidence + fix status (this is the "full evidence" doc the fix card
  spec referenced; attempt 1 never committed it).
- Board: filed **ADA-1405** `ada-voice-land-text-mode-session-persist`
  (backlog, high) — push local branch first, rebase, merge, `deploy-ada.sh`
  idc03, verify a new session-summary doc appears.

## How to verify

- `git show` this branch: the job yml exists.
- Board: `GET /cards?id=ada-voice-land-text-mode-session-persist` → ADA-1405.
- Post-deploy check (on the ADA-1405 card): close a `?mode=text` session →
  MDDB `ada-ha-recall-summary-<instance>` gains a `kind=session-summary` doc
  dated today; next Sun 09:45 `memory-distill` reports >0 new docs.

## Notes / residual

- Oct 17 → deploy window will never produce summary docs (transcripts exist;
  optional backfill noted in the job doc followups).
- Session `reports/*.json` share the same `persist()` gate — the AUD-0021
  "reports stopped 10-17" evidence is the same root cause.

lessons:
- A dispatch "verified/auto-closed" verdict only proves the *chaba* branch
  merged — cross-repo fixes (ada-voice) can be reported done while the actual
  artifact sits unpushed on the runner host. Always check `git ls-remote` on
  the target repo before trusting a fix card's done state.
- Local-only fix branches on runner hosts are one merge-sweep GC away from
  loss — file the land-it card immediately and mark "push first" as step 1.
- `search_documents` `sort=-added_at` did not return newest-first on this
  MDDB; filter on `meta.date`/key instead for "newest doc" checks.
- When a prior dispatch fails with "no commits", its card comms still carry
  the findings — read them first, then spend the attempt committing the
  deliverable rather than redoing the investigation.
