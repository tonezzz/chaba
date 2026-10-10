# Messaging-lane standard (TG / LINE / future)

One bot lane per persona. Every lane follows the same contract — new lanes copy this checklist.

## Contract

1. **Bot per lane** — own token; never share tokens across personas.
2. **Speaker tag** — every outbound message carries `[<speaker>]` prefix via
   `TG_SPEAKER_TAG` in the lane's env file (`~/.config/secrets/telegram-*.env` on idc03).
   Canonical tags: `ada` (main lane), `kaewta` (kk-ha lane), `chaba`, then one tag per
   future persona — lowercase, single word.
3. **Inbound identity** — `TELEGRAM_ALLOWED_CHAT_IDS` (groups that may talk) +
   `TELEGRAM_USER_CALLERS` (`<uid>:<key-name>` — sender → person, not the group).
   A sender's first message must be captured and mapped before their policy works.
4. **Outbound push** — every relay exposes loopback `POST /send {chat_id?, text?, photo_url?}`
   on `TG_LISTEN` (one port per lane; registered here). Proactive messages go through it —
   assistants never call the Telegram API directly.

| lane | bot | chat | tag | TG_LISTEN | state |
|---|---|---|---|---|---|
| ada | ada bot | 8960073266 (Tony DM), -5410424865 | ada | 127.0.0.1:8911 | live |
| kk | kk_ha_bot | -5597972933 (KK-HA) | kaewta | 127.0.0.1:8913 | live |
| line | — | — | — | — | blocked: Yomi token revoked (PIN re-login on Tony's phone) |

## Verify a lane

```bash
curl -X POST http://<TG_LISTEN>/send -H 'content-type: application/json' \
  -d '{"text": "[<tag>] relay check"}'
# -> {"ok":true,"chat_id":<id>} and the tagged message appears in the group
```

## New lane checklist

- [ ] bot token → lane env file on idc03
- [ ] `TELEGRAM_ALLOWED_CHAT_IDS`, `TELEGRAM_USER_CALLERS` (map senders as they appear)
- [ ] `TG_SPEAKER_TAG`, `TG_LISTEN` (pick unused loopback port)
- [ ] unit file cloned from a working lane, enabled
- [ ] verify: push test + real inbound → reply carries `[tag]`
- [ ] add row to the table above + bump member-tg/msg-lane in ssot.procedures.yml

## Voice-message handling (approved 2026-10-10)

When a lane (TG/LINE voice note, or a voice turn bridged into a text lane)
receives a **voice message**, the assistant replies in this order:

1. **Transcript echo** — first message in the *same channel*: the text
   transcript of what was heard, prefixed `[<speaker>]`, so the channel
   has a readable record of what was actually understood.
   Format: `[kaewta] 🎙 "<transcript>"`
2. **Result** — the answer/action outcome in the *same channel* —
   `[kaewta] <reply>` (text, never voice-only on a lane).
3. **Home-channel mirror** — the same transcript + result is mirrored to
   the lane's *home channel* so each house has one place to see its
   assistant's lane activity:
   - ada → tony-ha lane (Tony TG DM + group)
   - kaewta → kk-ha lane (KK-HA group)
   - chaba → chaba lane when it exists
   Mirror format: `[kaewta] (via tg-kk) 🎙 "<transcript>" → <one-line result>`
   — no full repost of long answers, one line of outcome.

**Why**: voice is ephemeral — a lane with no transcript is unauditable, and
each house's channel should show everything its assistant did for that
house, regardless of which lane the request arrived on.

**Rules**: transcripts are verbatim (no cleanup); results summarize to one
line on the mirror; failures report as `(no reply)`/`(failed: <err>)`, never
silence; the same `[speaker]` tag applies everywhere.
