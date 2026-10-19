# Dispatch outcome — tg relay TG_LISTEN env drift (OPS-0744)

## Decision

**The binds are canonical; nothing ever "picked +1".**
`backend/tg_relay.py` binds exactly `TG_WEBHOOK_LISTEN` — there is no
auto-increment/fallback path (verified in source and by the fact that both
relays bound 8913/8917 at the Oct 18 20:36 restart, before the card was
filed). The apparent drift was **dead `TG_LISTEN=` lines** in
`telegram-kk-bot.env` (claimed 8912 — actually the LINE relay's port) and
`telegram-mn-bot.env` (claimed 8916): `TG_LISTEN` is only the code alias /
docs shorthand, the real env var is `TG_WEBHOOK_LISTEN`, which already held
the correct ports.

## What happened / what was found

- The card's fix had already been applied ~16:30 ICT today by an earlier pass
  on the same card (board comm "RESOLVED" at 16:31, batch rewrite of the four
  kk/mn env files at 16:30:47 via ssh from idc02): dead `TG_LISTEN` lines
  deleted, `ADA_TG_SEND_URL` added to `ada-kk.env` (:8913) and
  `ada-ai-kraut.env` (:8917), both lane backends restarted 16:30:52.
- **I verified all of it live on idc03**: `ss -tlnp` maps 8911→ada-tg-relay,
  8912→ada-line-relay, 8913→ada-tg-relay-kk, 8914→ada-stt,
  8917→ada-tg-relay-mn; journal "send listener" lines confirm 8913/8917 since
  Oct 18 20:36; `/proc/<pid>/environ` of the restarted ada-kk / ada-ai-kraut
  backends carries the new `ADA_TG_SEND_URL`s.
- **chat_send relay-endpoint map: no drift.** `tool_runner/chat.py`,
  `openrouter_provider.py`, `ada_track_device.py` all use
  `ADA_TG_SEND_URL`/`ADA_LINE_SEND_URL` with ada-lane defaults (tg :8911,
  line :8912). The deeper real bug the fix resolved: kk/mn backends had no
  override, so their chat_send posted to :8911 — a silent cross-lane send
  failure. Dev lanes (ada-dev, ada-kk-dev, ada-pi-pwa) keep :8911 on purpose.
- No other surface references 8915/8916/8918 (health checks, caddy, docs).

## Changes made (worktree, dispatch branch)

- `docs/kb/msg-lane-standard.md` — corrected env var name
  (`TG_LISTEN`→`TG_WEBHOOK_LISTEN`, with the dead-config warning), added the
  mn lane row (KrautMNBot :8917), added the 891x allocation table and the
  `ADA_TG_SEND_URL` checklist item.
- `docs/ssot/ssot.procedures.yml` — `tg-lane-setup` entry: same var-name fix,
  list of taken ports, added the `ADA_TG_SEND_URL` backend-env step.
- `stacks/idc03/ada-tg-relay-kk/stack.yml` + `stacks/idc03/ada-tg-relay-mn/stack.yml`
  — new stack entries (were missing).
- `docs/ssot/jobs/ada/2026-10-19-tg-relay-env-drift-decision.yml` — decision
  record with verification commands.

## Board

Posted a verification comm; `do_finish` accepted — card is in **review**
(status done) pending human confirmation.

## How to verify

```bash
ssh idc03 'ss -tlnp | grep -E "891[0-9]"'
ssh idc03 'grep LISTEN ~/.config/secrets/telegram-*.env'
ssh idc03 'tr "\0" "\n" < /proc/$(systemctl --user show ada-kk -p MainPID --value)/environ | grep ADA_TG_SEND_URL'
```
