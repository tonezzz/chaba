# Telegram conversation and group standard

Status: defined 2026-10-26

Telegram is a delivery surface, not the source of truth. Conversations,
news, cards, and Education remain in their canonical stores.

## Group policy

Create a new group only when at least one boundary differs:

- owner/member set;
- privacy or retention requirement;
- persona/lane;
- purpose and notification rate;
- escalation or tool permission.

Otherwise reuse the existing group and add a topic/thread or a clear prefix.
Do not create one group per experiment.

Every group gets a registry record containing:

```yaml
chat_id: "-5410424865"
name: "Tony — Ada"
purpose: conversation | news | operations | family | experiment
bot: ada-tg-relay
owner: tony
members: [tony]
allowed_callers: [tony]
source_of_truth: "WP/MDDB/card/etc."
notification_policy: "one morning digest; urgent exceptions only"
privacy: private
retention: "follow Telegram + relay policy"
kill_switch: "~/.config/<job>.off"
```

Never put bot tokens, user tokens, or private message content in the registry,
Git, a report, or a card.

## New-group procedure

1. **Name and purpose** — write one sentence and choose conversation/news/
   operations/experiment.
2. **Existing-group check** — search the registry and configured
   `TELEGRAM_ALLOWED_CHAT_IDS`; do not guess from a display name.
3. **Create/configure** — add the correct bot, set a description and pinned
   contract, and keep admin rights minimal.
4. **Identify** — send a unique probe such as `tg-probe <timestamp>` and
   confirm the numeric `chat_id` from the relay/webhook log. A name alone is
   not proof.
5. **Allowlist** — add the chat and approved sender IDs to the relay secret
   through the declared secret-management path; restart only the affected
   unit.
6. **Consumer test** — send one dry-run notification through `board_notify`
   and have the owner confirm receipt in the intended group. Verify the
   actual message surface, not just a healthy relay.
7. **Register** — commit the non-secret registry record and card the
   purpose/owner/kill switch.
8. **Enable automation** — only after the consumer confirms. Keep a
   kill-switch file and rate limit.

## News delivery contract

The News CPT and morning brief are canonical. Telegram receives a projection:

- one morning summary with 3–7 items and links;
- one message per urgent/high-confidence exception;
- no raw-feed flood;
- duplicate suppression by story ID and date;
- link back to the private brief/Education lesson;
- delivery state and last cursor are durable;
- failed delivery retries without advancing the cursor.

Tony-HA may receive the same brief through `board_notify`'s HA channel, but it
must not create a second news database or a second editorial summary.

## Verification

A group is **configured** when the relay is active, the chat is allowlisted,
and the webhook is healthy. It is **ready** only after a human confirms the
dry-run message in the intended group. A configured group with no consumer
confirmation must not receive scheduled news.
