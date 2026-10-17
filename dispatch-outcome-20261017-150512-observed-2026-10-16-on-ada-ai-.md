# Dispatch outcome — text-mode-chat-send-broken (2026-10-17)

**Card:** `text-mode-chat-send-broken` · **Runner:** idc02
**Repos touched:** `ada-voice` worktree `~/CascadeProjects/ada-wt-text-mode-notify`
(branch `dispatch/20261017-150512-observed-2026-10-16-on-ada-ai-`, commit
`f4c4625`, off `origin/main` a9a8cca — NOT pushed) + this chaba dispatch
worktree (SSOT job trail).

## Incident

2026-10-16 on ada-ai-kraut: `chat_send notify failed: timed out` (~14s),
then `WARNING pwa_server: session=... notify failed: AttributeError:
OpenRouterTextProvider object has no attribute notify_or_defer`. Kraut's
`chat_send` (dub-sample video, channel=line) ran its background job, but
the completion note POST to `/api/notify` hard-crashed on the text
provider — and the handler had likely already stalled on an unbounded
`ws.send_text` (notify_voice frame), matching the caller-side ~14s
timeout before the AttributeError logged.

## What changed (ada-voice, commit f4c4625)

### `backend/openrouter_provider.py`

- **`notify_or_defer(text, urgent=False) -> str`** — text-mode port of the
  Live split, same `interrupted|context|queued` contract `/api/notify` maps.
  - `urgent`, relay channels (line/telegram/tg): spontaneous model replies
    are drained-and-dropped by the relay reader between turns, so the note
    pushes **out-of-band via the relay `/send` endpoint** — the same path
    `chat_send` takes, keeping the relay's own per-chat guards authoritative
    (`LINE_LANE_ALLOW`/`LOCK`, `TG_PUSH_DENY` on the mn-ha group). Push
    targets the `SESSION_CHAT`-bound chat (lane default room when unbound).
    A denied/unreachable push degrades to a context note → `'queued'`,
    never lost.
  - `urgent`, live-read clients (web/pwa/scenarios): kicks a completion —
    the inline-announce analog of Live's interrupt → `'interrupted'`.
  - non-urgent: silent context note appended to `_turns` → `'context'`
    (Live's `turn_complete=False` equivalent — `_turns` IS the history, no
    flush queue needed).
  - closed provider raises `RuntimeError("provider is not connected")` —
    `/api/notify`'s retry loop keys on that phrase.
- **`queue_context_note(text)`** — same contract Live exposes; the
  channel-mirror and command-lane callers were silently dropping notes on
  text sessions (`suppress()`-wrapped sites, invisible until now).
- **`_relay_push(chan, text)`** — loopback POST to `ADA_TG_SEND_URL` /
  `ADA_LINE_SEND_URL`, 20s timeout via `asyncio.to_thread`.

### `pwa_server.py`

- `api_notify`: `notify_voice` `ws.send_text` wrapped in
  `asyncio.wait_for(timeout=4)` — a half-dead relay socket could stall the
  handler past the caller's own timeout.

### `tests/test_openrouter_provider.py` — 5 new cases

context append, urgent relay push (endpoint/chat_id/session record),
deny→queued fallback, inline kick on web, closed-session error,
`queue_context_note`.

## Not changed

`chat_send` itself — LINE `/send` already degrades `video_url` to a text
link via `_video_msgs`, so the media-degrade clause is covered relay-side.
`TG_PUSH_DENY` is env-side; routing urgent pushes through `/send` keeps the
guard in force rather than bypassed.

## Verification

- `pytest tests/test_openrouter_provider.py` — **13/13 pass**.
- `pytest tests/ -q` — **1542 passed, 7 skipped**; 3 failures
  (`test_non_dict_return_wraps_in_output`, `test_ok_dict_passes_through`,
  `test_dynamic_tool_executes`) reproduce identically on **pristine
  `origin/main`** — a host-environment `capture_reminder` injection,
  unrelated to this diff.
- `scripts/tool-lint.py` — clean.
- `node scripts/ssot-validate-all.mjs` — 2556/2556 valid (chaba side).

## How to verify / ship

```bash
cd ~/CascadeProjects/ada-wt-text-mode-notify
git log --oneline -1            # f4c4625
PYTHONPATH=~/CascadeProjects/ada-voice/.venv/lib/python3.12/site-packages \
  <pytest-venv>/bin/python -m pytest tests/test_openrouter_provider.py -q
```

Ship path: merge-sweep pulls the dispatch branch into tony-dell's served
ada-voice checkout → `deploy-ada.sh` on idc03 (pre-flight gates, session
drain, restarts). Until deployed, `/api/notify` still AttributeErrors on
prod text-mode sessions.

## Follow-ups

- The 3 pre-existing suite failures on this host (`capture_reminder`
  polluting tool-runner results) may be worth a card — they fail the
  deploy gate's `pytest -x` for anyone gating on idc02.
- **board-api on tony-dell returned 502** for the final comms post
  (retried ~3min apart; the pickup comment landed at session start —
  the service appears to have died since, consistent with the
  2026-10-16 tony-dell collapse). Card comms carrying this result may
  need a manual re-post once board-api recovers; this file + the job
  YAML carry the full record.
