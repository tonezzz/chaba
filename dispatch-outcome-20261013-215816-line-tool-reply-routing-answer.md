# Dispatch outcome — line-tool-reply-routing-answers-leave-th-5c73e7

## What was wrong

A persona's `chat_send` inside a LINE turn left the originating chat.
`chat_send` posts a bare `/send` to `ada-line-relay` (`backend/tool_runner/
chat.py` → `http://127.0.0.1:8912/send`); with `to` empty the relay resolved
`_recent_chat[instance]` → `LINE_LANE_DEFAULT[instance]` → first allowed
user. `_recent_chat` was written keyed by **persona name** (`kaewta`) in
`_deliver_turn` but read keyed by **`ADA_INSTANCE_ID`** (`kk`) — a dead map —
so every bare send landed in the lane default room or the owner's DM.
Under concurrency the deeper bug remained anyway: "most recent chat" is not
"the chat this turn came from".

## Fix (ada-pi staged drop 6, base `main` @ `98c8e26`)

Reply-context binding end to end:

- `backend/line_relay.py` — `ChatSession.chat_id`; `ensure()` adds
  `&chat_id=<chat>` to the ws URL; `_session()`/`_deliver_turn()`/image path
  thread the room or DM chat through; `/send` records each delivered target
  under the instance key (fixes the dead-map mismatch).
- `backend/tool_runner/common.py` — `SESSION_CHAT` registry
  (session_id → {channel, chat_id}) + `session_chat_id(runner, channel)`
  reading `_CALLER_SESSION` first (race-free per-call var).
- `backend/tool_runner/chat.py` — `_chat_send_run` defaults `to`/`chat_id`
  to the session's bound chat when `to` is empty, per channel (a LINE-bound
  id never feeds a telegram send). Explicit `to=` still wins.
- `pwa_server.py` — `/ws` reads `?chat_id=`, binds `SESSION_CHAT` at connect,
  pops at teardown.
- `backend/tg_relay.py` — same `&chat_id=` on the Telegram ws connect (same
  bug class; the binding is channel-agnostic).
- Tests: new `tests/test_line_reply_context.py` (9 tests) +
  `_FakeSession` kwarg fix in `test_line_relay_group.py`.

## Deliverables (this worktree)

- `integrations/ada-pi/backend/line_relay.reply-routing.patch`
- `integrations/ada-pi/backend/tool_runner.reply-routing.patch`
- `integrations/ada-pi/backend/tg_relay.reply-routing.patch`
- `integrations/ada-pi/backend/test_line_relay_group.reply-routing.patch`
- `integrations/ada-pi/pwa_server.reply-routing.patch`
- `integrations/ada-pi/tests/test_line_reply_context.py` (new ada-pi test)
- `integrations/ada-pi/README.md` — Drop 6 section (install steps + contract)
- `tests/ada/test_line_reply_routing.py` — chaba-side drop gate (7 tests)
- `tests/ada/test_line_file_doc_ingest.py` — tolerate the drop-2 patch being
  already merged upstream (pre-existing failure: staged patch vs moved HEAD)
- `docs/ssot/jobs/ada/2026-10-13-line-tool-reply-routing.yml` — job trail

## Verified

- ada-pi `main` @ `98c8e26` + patches (clone in /tmp): `pytest tests/` —
  1365 passed / 4 skipped; `test_line_relay_group` 28/28;
  `test_tool_runner` 274/274; `tool-lint` clean.
- Chaba side: `pytest tests/ada` — 61 passed. Drop test applies all 5
  patches to a clean ada-pi copy, compiles them, drives the patched relay
  (ws URL carries chat_id, `_session` threads it, `/send` keys
  `_recent_chat` by instance) and the patched `session_chat_id` helpers.
- Not deployed (dispatch rules): install per README drop 6 on
  ~/CascadeProjects/ada-pi, `deploy-ada.sh` on idc03, restart
  `ada-line-relay` + `ada-tg-relay` + lane backends.

## Residual / follow-ups

- Context-free sends (proactive, `ada_track_device` watches) keep the
  fallback chain — now correctly keyed; `line-proactive-persona` owns
  explicit member addressing.
- Sibling card `line-delivery-send-actual-images` inherits the routing rule
  (same `/send`); the image-payload work itself is separate.
- Live verify after deploy: a chat_send-triggering ask in room C822 lands in
  C822, not a DM.

lessons:
- ada-pi lives outside this repo — deliver as staged patches under
  integrations/ada-pi/ + chaba-side test; clone tonezzz/ada-pi to /tmp as
  diff base (github read works without creds).
- `_recent_chat` was a dead map: written persona-keyed, read
  instance-keyed — grep both write AND read sites when judging a fallback.
- `/tmp/ada-pi-clean` already existed as a stale checkout — name scratch
  dirs uniquely or the worktree add silently no-ops.
- Staged record patches drift once merged upstream; chaba drop tests should
  tolerate "already applied" (feature-marker check) instead of hard-failing
  `git apply`.
