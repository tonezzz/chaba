# Dispatch outcome — ada-voice text-mode sessions never call conversation.persist()

Card: `ada-voice-text-mode-sessions-never-call-e007bd` (ADA-1400), parent
`ada-session-summary-inflow-stalled`.

## What changed

The fix lives in the **ada-voice** repo, not chaba. Following the
established dispatch pattern (cf. `ada-voice-wt-ada-command-publish`), I
created a dedicated ada-voice worktree on this host:

- Worktree: `/home/tony/CascadeProjects/ada-voice-wt-text-mode-persist`
- Branch: `dispatch/text-mode-session-persist` — 1 commit `c14758b`
  ahead of `origin/main` `a060335`; **NOT pushed** (dispatch rails)

Commit contents:

- `backend/openrouter_provider.py` — `OpenRouterTextProvider.close()` is
  now idempotent (`if self._closed: return`, matching
  `GeminiLiveProvider.close()`) and fires
  `asyncio.create_task(self.conversation.persist())` when a conversation
  is attached — the same fire-and-forget shape the Live provider uses so
  ws teardown isn't blocked on MDDB/NotebookLM. This is the entire fix:
  text-mode sessions (`?mode=text`, `ADA_TEXT_ONLY_CALLERS`,
  `ADA_TEXT_ONLY_CHANNELS` default telegram/tg/line, plus chat/web via
  the ada-ha-tony drop-in) now produce `kind=session-summary` MDDB docs,
  `reports/*.json`, extract candidates/actions, and daily rollups —
  restoring the inflow `ada-session-summary-inflow-stalled` measured as
  dead since early Oct.
- `tests/test_openrouter_provider.py` — +2 tests:
  `test_close_persists_conversation_once` (persist fires exactly once
  across two `close()` calls) and `test_close_without_conversation`.
- `docs/ssot/jobs/ada/2026-11-25-text-mode-session-persist.yml` — job
  trail: root cause, design notes, deploy + verification steps.

Design notes (verified before patching):

- `persist()` self-guards on `no_persist` and empty `_turns`, so
  scenario/test sessions and content-free sessions are unaffected.
- Turn population confirmed: `pwa_server.py` /ws handler calls
  `conversation.add_user()` for `type:text`/image turns and the provider
  calls `conversation.add_assistant()` on replies — `_turns` is
  populated, so `persist()` won't early-return.
- Full `persist()` (not a slim variant): the NotebookLM
  `add_text_source` leg is already gated on `client.configured` and
  failure-safe; `channel` is recorded on the conversation so summaries
  can distinguish surfaces. The degraded-fallback provider
  (`pwa_server.py` ~1449) passes the same conversation and gets persist
  for free.
- Double-close safety: the idempotence guard prevents a second
  `persist()` on teardown paths that close the provider twice.

## Verification

- `pytest tests/test_openrouter_provider.py` — 15 passed
- `pytest tests/test_text_lane_routing.py` — 8 passed
- Full suite `pytest tests/ -x -q` — **1982 passed, 7 skipped** (2m38s;
  warnings all pre-existing)
- `python3 scripts/tool-lint.py` — clean (69 warnings, none new)

## Deliberately NOT done

- **No push/merge** — branch left for review per dispatch rails.
- **No deploy** — `deploy-ada.sh` on idc03 runs only after merge to
  `origin/main` (it ff-merges the served checkout itself).

## How to verify / next steps

1. Review/merge `dispatch/text-mode-session-persist` in
   `~/CascadeProjects/ada-voice` (or push the branch to origin).
2. On idc03: `~/.local/bin/deploy-ada.sh` (drains live /ws sessions,
   runs tool-lint + pytest gates, restarts services).
3. Post-deploy check: end a `?mode=text`/telegram/line session, then
   confirm a new `kind=session-summary` doc lands in the lane's
   `ada-ha-recall-summary-*` MDDB collection and LiteLLM SpendLogs show
   `tool=session_summary`/`session_report` calls resuming.
4. Optional backfill: sessions since ~2026-10-17 have durable per-turn
   transcript archives (`durable_transcript`), so a replay could
   regenerate summaries for the gap — out of scope here, candidate for
   a follow-up card if Tony wants the hole filled.

lessons:
- ada-voice dispatches from chaba cards follow the sibling-worktree
  pattern: `git worktree add ~/CascadeProjects/ada-voice-wt-<slug> -b
  dispatch/<slug> origin/main`, commit there, never push — the merge +
  `deploy-ada.sh` on idc03 stays a human/review step.
- `OpenRouterTextProvider` keeps its own `_turns` history AND mirrors
  into `conversation` — `add_user` is called by the pwa_server /ws
  handler (not the provider), `add_assistant` by the provider; check
  both sides before assuming `persist()` sees turns.
- A venv from a sibling ada-voice worktree
  (`ada-voice-wt-*/.venv/bin/python`) runs another worktree's full
  pytest suite cleanly — no per-worktree venv needed.
