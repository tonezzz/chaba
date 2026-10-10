# Dispatch outcome — fix-gate-entity-in-home-assistant-1df995

## Summary

`cover.front_gate` does not exist on any Home Assistant instance — and
never did. The gate lives on **michael-ha** as `cover.gate_motor` (Tuya
curtain-type cover with no position feedback). On **tony-ha** there are
zero cover/door/lock entities at all, so `home_search` on the ada-tony
instance can never find the gate; only the ada-michael instance sees it.
A secondary issue: `cover.gate_motor` rests at state `unknown` (normal for
feedback-less Tuya covers — it only reports `opening`/`closing` while
moving), so the entities endpoint flags it `available: false`; if
`home_search` drops unavailable entities, the gate is hidden even on
ada-michael.

## What changed (3 new files, no modifications)

- `docs/ada-memory/home/gate-control.md` — device-alias/procedure doc for
  the shared `home` memory bank: maps "front gate / the gate" to
  `cover.gate_motor`, `button.gate_motor_my_position`,
  `switch.living_room_front_gate`, `switch.sonoff_10010b42b6` (the gate
  *light*); warns that `unknown` state is normal, that
  `cover.front_gate` does not exist, that only ada-michael can actuate it,
  and that movement requires `confirmed=true`. Syncs to
  `ada-ha-bank-home` via `ada-memory-sync.timer` once merged into the
  chaba-vault checkout.
- `docs/ssot/kanban/cards/home-search-unknown-state-entities.yml` —
  follow-up card queued for repo `ada-pi` (self-contained spec): verify
  `home_search` does not filter out `unknown`/`unavailable`-state entities;
  if it does, include them flagged and add a unit test.
- `docs/ssot/jobs/home-assistant/2026-10-10-gate-entity-home-search.yml` —
  investigation record with evidence, verify steps, and open questions.

## Evidence (verified live, read-only GETs)

- `GET /apps/ha/ada-tony/api/home-assistant/entities` → 32 entities,
  zero covers; `events?query=cover|door|lock|gate&hours=2160` → scanned 0.
- `GET /apps/ha/ada-michael/api/home-assistant/entities` → 270 entities
  incl. `cover.gate_motor` (state `unknown`, `available:false`),
  `button.gate_motor_my_position` (available),
  `switch.living_room_front_gate` "Front Gate" (available, off since
  2026-10-01), `switch.sonoff_10010b42b6` (front-gate light).
- `entity-events?entity_id=cover.gate_motor` → flaps
  `unavailable`(~10–25 s)→`unknown` several times/hour; at `unknown`
  since 2026-09-30 11:47 — consistent with the documented no-feedback
  behavior in `docs/kb/ada-ha-gate-incident-2026-09-16.md`.

## How to verify

1. `curl https://idc03.taila0626a.ts.net/apps/ha/ada-michael/api/home-assistant/entities`
   — gate entities present as above.
2. After merge + the next `ada-memory-sync.timer` run, ask ada-michael
   "how do I open the front gate" — recall should surface the alias doc;
   actuation still requires explicit confirmation (safety gate).
3. The ada-pi follow-up card will verify the search filter itself.

## Open questions for Tony (posted on the card)

- Which Ada instance did the user ask? If ada-tony, the miss is instance
  isolation by design — cross-instance gate control would be a product
  decision, not a bug.
- Is `switch.living_room_front_gate` a working gate trigger? Needs one
  manual test on michael-ha before Ada relies on it.
