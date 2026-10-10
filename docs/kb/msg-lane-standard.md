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
