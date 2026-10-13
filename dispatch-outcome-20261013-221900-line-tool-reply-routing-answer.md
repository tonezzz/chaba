# Dispatch outcome — LINE tool reply routing: answers stay in the originating chat

Card: `line-tool-reply-routing-answers-leave-th-5c73e7` (ADA-0606, high)
Result: **done — staged ada-pi Drop 8, tested, committed on the dispatch
branch (not pushed, not deployed).**

## What was wrong

A bare `chat_send` — the documented "reply in this room" path — left the
originating chat, landing in the lane default room or the owner's DM.
Two compounding mechanism breaks in `backend/line_relay.py` `/send`:

1. `_recent_chat` (the default target when `to`/`chat_id` is empty) was
   keyed by **persona** name (`ada`, `kaewta`) while the payload's
   `instance` field carries `ADA_INSTANCE_ID` (`tony`, `kk`) — the
   lookup could never match. Only instance `chaba` (persona name ==
   instance name) accidentally worked.
2. `_recent_chat` was written only inside `_deliver_turn`, which runs
   only for voice-transcript turns. Plain text/image/file turns never
   recorded their chat at all, so the recent-room fallback was almost
   always empty and resolution fell through to `LINE_LANE_DEFAULT` or
   `next(iter(_allowed_users()))` — the owner's DM.

## What changed (staged patches vs ada-pi `main` @ `98c8e26`)

- `integrations/ada-pi/backend/line_relay.reply-routing.patch`
  - `ChatSession.chat_id` + `?origin_chat=<chatId>` on the ws connect —
    pins the chat the session serves (exact origin binding).
  - `_reader` learns persona→instance from the backend's `ready` hello
    (`_ws_instance`; self-report wins). `LINE_PERSONA_INSTANCE` env is
    the configured fallback.
  - `_note_recent()` records under BOTH persona and instance keys, and
    now runs on every routed turn path (`_deliver_turn` + the
    `handle_event` session point covering text/image/file/audio).
- `integrations/ada-pi/backend/pwa_server.reply-routing.patch` — `ready`
  frames carry `instance` (`ADA_INSTANCE_ID`); `voice_socket` stashes
  `?origin_chat=` into `tool_runner.session_origin[session_id]`
  (getattr-guarded) and pops it at close.
- `integrations/ada-pi/backend/tool_runner.reply-routing.patch` —
  `session_origin` dict on the runner; `_chat_send_run` resolves the
  calling session's origin via the `_CALLER_SESSION` ContextVar
  (race-free; `create_task` propagates context) and sends
  `chat_id = to or origin`. Explicit `to=` always wins.
- `integrations/ada-pi/README.md` — Drop 8 section (files, install,
  contract, residuals); intro renumbered (was a duplicated "6").
- `docs/ssot/jobs/ada/2026-10-13-line-reply-routing.yml` — job record.
- `tests/ada/test_line_reply_routing.py` — 22 tests including an
  end-to-end `/send` through the real route handler (stubbed
  Starlette/uvicorn) and the ast-extracted `_chat_send_run` payload.

## Resolution order after the drop

explicit `to`/`chat_id` → origin_chat pin → `_recent_chat[instance]`
(600s) → `LINE_LANE_DEFAULT` → owner DM (unchanged last resort).
`LINE_LANE_LOCK`/`LINE_LANE_ALLOW` gates still run after resolution.

## Verification

- `pytest tests/ada/` → **102 passed** (scratch venv `.cache/venv`;
  `ADA_PI=.cache/ada-pristine` — a pristine ada-pi worktree at `98c8e26`).
- `git apply --check` on all 3 patches: clean on **pristine** `98c8e26`
  AND on a tree with drops 5–7 applied — install order is free.

## To ship

Apply the three patches on tony-dell's ada-pi checkout (README Drop 8),
commit + push, deploy-ada.sh on idc03 (runs tool-lint + pytest gates),
restart `ada-line-relay` **and** the lane backends (the ready/
origin_chat handshake needs both sides). Optional env:
`LINE_PERSONA_INSTANCE="ada:tony,kaewta:kk,chaba:chaba"` covers
pre-connect lookups.

## Residuals / notes

- Two rooms on the same instance inside 600s with no origin pin still
  picks most-recent — the `origin_chat` pin removes this for LINE
  sessions; notify/voice sessions keep the fallback chain by design.
- `to=<member name>` still DMs that member (documented contract);
  `ada_track_device` pushes still go to the owner DM (device alerts).
- tg_relay has no lane layer — unchanged.
