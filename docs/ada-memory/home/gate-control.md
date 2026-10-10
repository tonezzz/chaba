---
key: gate-control
kind: procedure
status: active
subject: front-gate
attribute: control
scope: shared
source: vault
written_by: devin
last_verified: 2026-10-10
applies_to: [cover.gate_motor, button.gate_motor_my_position, switch.living_room_front_gate, switch.sonoff_10010b42b6]
---

How to control the front gate (Michael site, michael-ha). There is no
`cover.front_gate` — that entity id does not exist on any instance. The real
gate entities on michael-ha are:

- `cover.gate_motor` ("Gate Motor") — the actual gate control, a Tuya
  curtain-type cover with no position feedback. `open_cover`/`close_cover`/
  `stop_cover` move the gate. Its state reads `unknown` at rest — that is
  normal for this device (it only reports `opening`/`closing` while moving);
  it also flaps to `unavailable` for ~10-25 s a few times an hour and
  recovers on its own. Do not tell the user the gate is broken or offline
  just because the state is `unknown`.
- `button.gate_motor_my_position` ("Gate Motor My position") — jogs the gate
  to its preset position. Inherits the gate's dangerous-entity flag.
- `switch.living_room_front_gate` ("Front Gate") — a switch named for the
  gate; steady `off` since 2026-10-01. Likely a relay tied to the gate —
  treat it as a secondary control, not the primary one.
- `switch.sonoff_10010b42b6` ("Light Front Gate") — the LIGHT at the front
  gate, not the gate itself.

Only the ada-michael instance can see or actuate these — tony-ha has no
gate, cover, door, or lock entities at all, so `home_search` on the tony
instance can never find the gate. If a user on the tony instance asks for
the gate, explain it lives on the Michael instance.

Moving the gate is dangerous-entity actuation: it requires the user's
explicit spoken confirmation and `confirmed=true` on the control call
(server-side safety gate — see the 2026-09-16 gate incident report). The
physical remote is kept in the hallway cabinet.
