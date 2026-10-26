# Dispatch outcome — ada-chat-card webchat push bind

Card: `ada-chat-card-cannot-receive-pushed-medi-099b01` (ADA-0743)
Runner: idc02 · 2026-10-26

## What changed

`stacks/tony-dell/{tony-ha,ada-ha}/www/ada-chat-card.js` (canonical HA
ChatUI copies, kept byte-identical), committed on the dispatch branch
(`67fbdfeff`) — not pushed:

1. **Session bind** — `_connect()` appends
   `&channel=web&chat_id=web-<member-or-device>` to the ws URL so
   `webchat_deliver` (chat_send channel=web, POST /api/webchat/send) can
   reach the card. `web` is not in ADA_TEXT_ONLY_CHANNELS → Live
   provider unchanged.
2. **Member resolution** — new `_pushChatId()`: `member:` config →
   lane's caller name for the key (`GET /api/auth/status`, ha-\*/admin
   names excluded) → HA login's linked `person.<slug>` → `instance`
   (lane member) → `web-<device8>` fallback. On tony-ha → `web-tony`;
   mn-ha → `web-michael` — the same thread ids senders already use.
3. **chat_push render** — `_handleControl` case → `_chatPush()`: Ada
   bubble, text via `_fillBubble`, `image_url` → `<img>`,
   `video_url` → `<video controls>`; non-http urls and empty pushes
   dropped. ws close 4403 gets a readable "key lacks the 'chat'
   capability" line.

## Verification

- **DOM-stub harness** (`/tmp/acc-harness.js`): 17/17 checks — all
  member-resolution tiers, ws URL contains `channel=web` +
  `chat_id=web-tony`, push bubbles render text/img/video-controls,
  empty and `javascript:`-url pushes drop.
- **Live lane** (throwaway `pwa_server:app` on idc02:8013, latest
  ada-voice main): bound ws received `chat_push` frame after
  `POST /api/webchat/send` (delivered=1, text + image_url verbatim);
  second send with no session → `parked:true`; fresh bound ws →
  `ready` then parked push flushed. Used `mode=text` for the verify
  connect — both fleet Gemini projects are spend-capped until
  2026-11-01 (Live connect 1011s everywhere); the bind/deliver/park/
  flush path is provider-agnostic and delivery works even pre-`ready`.
- **Prod**: `POST /api/webchat/send` on ada-tony/ada-michael/ada-kk/
  ada-dev all return 401 — endpoint exists fleet-wide, key-gated.
- `ada-lab.service` on idc02 was ff-pulled (4 commits) + restarted —
  its process predated the webchat endpoints (Oct 7); it now serves
  current main. Staging checkout left clean.

## Not done / follow-ups

- Browser-level check on a real HA dashboard (card self-mints via
  `script.ada_voice_key` — can't reproduce outside HA). After merge +
  `push-dashboard.py` deploy: open Chat tab on tony-ha, POST
  `/api/webchat/send` `chat_id=web-tony`, watch the bubble land.
  Bump `?v=` on the resource URL when deploying so browsers drop cache.
- `ada-voice/pwa/cards/ada-chat-card.js` (PWA variant) is a different
  file in a different repo — same gap if PWA push is wanted.
- Trail: `docs/ssot/jobs/ada/2026-10-26-ada-chat-card-webchat-push-bind.yml`.
