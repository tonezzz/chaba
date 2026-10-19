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
   on `TG_WEBHOOK_LISTEN` (the real env var in `telegram-<lane>-bot.env`; the
   `tg_relay.py` code alias is `TG_LISTEN` — a bare `TG_LISTEN=` line in an env
   file is dead config, it is never read). One port per lane; registered here.
   Lane backends reach it via `ADA_TG_SEND_URL=http://<listen>/send` in the
   backend env (`ada-<lane>.env`) — unset means the ada default :8911, which is
   wrong for any non-ada lane. Proactive messages go through it — assistants
   never call the Telegram API directly.

| lane | bot | chat | tag | TG_WEBHOOK_LISTEN | state |
|---|---|---|---|---|---|
| ada | ada bot | 8960073266 (Tony DM), -5410424865 | ada | 127.0.0.1:8911 | live |
| kk | kk_ha_bot | -5597972933 (KK-HA) | kaewta | 127.0.0.1:8913 | live |
| mn | KrautMNBot | 8960073266 (Tony DM), 80597829 (Michael DM), -5426710106 (mn group) | michael | 127.0.0.1:8917 | live |
| line | — | — | — | — | blocked: Yomi token revoked (PIN re-login on Tony's phone) |

Loopback 891x allocation: 8911 ada tg, 8912 line_relay, 8913 kk tg,
8914 ada-stt, 8917 mn tg. 8915/8916 are free.

## Verify a lane

```bash
curl -X POST http://<TG_WEBHOOK_LISTEN>/send -H 'content-type: application/json' \
  -d '{"text": "[<tag>] relay check"}'
# -> {"ok":true,"chat_id":<id>} and the tagged message appears in the group
```

## New lane checklist

- [ ] bot token → lane env file on idc03
- [ ] `TELEGRAM_ALLOWED_CHAT_IDS`, `TELEGRAM_USER_CALLERS` (map senders as they appear)
- [ ] `TG_SPEAKER_TAG`, `TG_WEBHOOK_LISTEN` (pick unused loopback port — see the
      891x allocation table above; never write `TG_LISTEN=`, it is ignored)
- [ ] `ADA_TG_SEND_URL=http://127.0.0.1:<port>/send` in the lane backend env
      (`ada-<lane>.env`) — without it chat_send posts to the ada default :8911
- [ ] unit file cloned from a working lane, enabled
- [ ] `TG_WHISPER_URL=http://tony-omen:8790/transcribe` in the lane env
      file — voice notes transcribe on the omen GPU (large-v3); local
      `TG_WHISPER_MODEL` fallback kicks in when the endpoint is down
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
