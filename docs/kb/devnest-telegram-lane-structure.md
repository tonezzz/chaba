# DevNest Telegram lane structure

Status: design ready, not enabled 2026-10-26

## Decision

Use a dedicated `TonyDvnstBot` and a dedicated relay lane. Do not reuse the
Ada, KK, or MN bot tokens. Do not put Telegram credentials or conversation
history inside the DevNest Home Assistant container.

The canonical secret filename is:

```text
~/.config/secrets/telegram-devnest-bot.env
```

`tg-tony-devnest-bot.env` is understandable, but it is less consistent with
the existing `telegram-bot.env`, `telegram-kk-bot.env`, and
`telegram-mn-bot.env` naming.

## Secret file

The host-only EnvironmentFile contains only secret/config values:

```text
TELEGRAM_BOT_TOKEN=<BotFather token>
TELEGRAM_ALLOWED_CHAT_IDS=<numeric group chat id>
TELEGRAM_USER_CALLERS=<numeric user id>:user-tonezzzz
TELEGRAM_MODE=poll
TG_PERSONA_NAME=DevNest
TG_WEBHOOK_LISTEN=127.0.0.1:8919
TG_SPEAKER_TAG=devnest
```

Never put this file in Git, `secrets.yaml`, the HA container volume, a pack,
an Education lesson, or a Telegram message.

## Relay and data separation

Run a dedicated `devnest-tg-relay.service` on idc03 with the secret file
above. The relay may call DevNest/board APIs, but it should not receive the
Ada/KK/MN credentials.

Conversation data is not a secret file. Store it separately:

```text
~/.local/share/devnest/telegram/
  updates.jsonl          # raw metadata, redacted message body policy
  conversations/
    <chat-id>/<thread>.jsonl
  state.json             # update offset/cursor
  artifacts/
    <job-id>/             # links/hashes, not secret payloads
```

Every conversation record should contain:

```json
{
  "chat_id": "-100...",
  "message_id": 123,
  "sender_id": 456,
  "sender_label": "tony",
  "at": "2026-10-26T...",
  "thread": "job|research|ops",
  "text_policy": "private-retained|metadata-only",
  "job_id": "optional",
  "artifact_ref": "optional"
}
```

Keep the DevNest HA sandbox independent. If it needs HA actions, mount only a
scoped HA token through its own `devnest-ha.env`; do not mount the Telegram bot
token into `devnest-ha`.

## Provisioning gate

1. Tony creates `TonyDvnstBot` with BotFather.
2. Tony creates or chooses the dedicated DevNest group and adds the bot.
3. Tony sends a unique first probe.
4. The relay discovers and records the numeric `chat_id`; the display name is
   not an identity.
5. Add the chat and approved sender IDs to the secret file.
6. Start the dedicated relay and verify its webhook/poll health.
7. Send one dry-run `DevNest test — <timestamp>` message.
8. Tony confirms receipt in the intended group.
9. Only then enable job-start/job-finish or morning-news notifications.

The board card is `OPS-0905`. Until steps 1–4 happen, the service stays
disabled and no token file is created.

## Message policy

- `#job` — start/claim/progress/done/fail with card and artifact refs.
- `#research` — short findings, sources, confidence, and Education link.
- `#ops` — health or human-gated requests only.
- One summary per job; no raw logs or token dumps.
- External actions, spend, production changes, and Telegram group changes
  require a human confirmation.
- A kill switch disables proactive sends without removing the bot.
