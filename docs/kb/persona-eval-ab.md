# Persona eval → variant → A/B → adopt — standard procedure

How to improve a persona (ada/kaewta/chaba/…) and prove it before shipping.
A persona = instance env + instructions + memory bank + model choice — there
is no weight training; "training" = iterating those four levers and measuring
with the scenario suite.

## 1. Measure the baseline

- Scenarios are yaml under ada-voice `tests/scenarios/` (unit-tier) and
  `tests/scenarios-live/` (drives real backends). Format: `TOUR_STANDARD.md`.
- Run: `scripts/scenario-benchmark.py --suite <suite>` on idc03 — writes a
  `kind: benchmark` doc to `ada-ha-scenario-reports` + the auto-report page.
- Policy gates in `tests/benchmark.yml` are non-negotiable bars
  (identity_confusion_guard, cross_instance_isolation, write-tools list).
- Scheduled: `ada-scenario-*.timer` (smoke hourly; tools/memory/reports weekly).

To cover a new behavior (e.g. kaewta shows a photo then engages nhong):
write the yaml FIRST — the scenario is the spec. Live LINE end-to-end
(bot webhook → reply) has no injection harness yet; drive the backend ws
directly or test in-group manually until one exists.

## 2. Build the variant

Clone the lane — every ada instance is `env + keys file + unit`:

- Copy `~/.config/secrets/ada-kk.env` → variant port (`:8009`), change
  `ADA_INSTANCE_ID` (or keep id and give the variant its own keys file name).
- Change ONE lever per round: prompt/instructions, model, tool set, or a
  seeded memory-bank delta — otherwise the score can't attribute the gain.
- Variant unit `ada-kk-b.service`; cgroup caps per ha-ada-isolation.md.

## 3. A/B

- **Toggle (today, zero code)**: flip the lane pointer —
  `LINE_NAME_BACKENDS=…,kaewta:ws://127.0.0.1:8009,…` in `line-bot.env`,
  restart `ada-line-relay`. Instant, reversible. Whole-lane swap.
- **Split A/B** (some senders → A, some → B): `LINE_CALLER_BACKENDS` in
  `line-bot.env` overrides the backend per sender — implemented in
  `line_relay.py` (`_caller_backends`/`_backend_url`, card
  `persona-ab-split-routing-relay`, OPS-0469 optional scope). Format:
  `caller=url` covers every persona that caller addresses;
  `caller@persona=url` scopes the override to one lane; `user-` prefixes
  are ignored on both sides; bare `host:port` gets `/ws` appended.
  Split config example — kk talks to variant A while everyone else
  (incl. nhong) stays on control:

  ```
  LINE_NAME_BACKENDS=ada:ws://127.0.0.1:8002,kaewta:ws://127.0.0.1:8007,chaba:ws://127.0.0.1:8004
  LINE_CALLER_BACKENDS=user-kk=ws://127.0.0.1:8009
  ```

  Scoped variant — only kk's chaba-lane turns go to the variant, other
  personas he addresses stay on control:

  ```
  LINE_CALLER_BACKENDS=user-kk@chaba=ws://127.0.0.1:8009
  ```

  An override also resolves a persona whose lane URL is empty
  (known-but-offline) — handy when the variant is the only backend up.
  Unmapped group members (no `LINE_USER_CALLERS` entry) always ride the
  lane pointer. Restart `ada-line-relay` after editing; removing the
  entries restores whole-lane routing instantly.
  **Status (2026-11-24):** staged as ada-voice drop #22 — three patches
  in `integrations/ada-voice/`:
  `backend/line_relay.persona-ab-split.patch`,
  `backend/test_line_relay_group.persona-ab-split.patch`,
  `env.example.persona-ab-split.patch` — verified `git apply --check`
  clean vs `origin/main` @ `2e9a1eeb` and `pytest
  tests/test_line_relay_group.py` green (32 tests). Until merged +
  deployed, toggling + alternating test windows remains the honest
  equivalent.
- **Shadow**: precedent in `command_lane.py` (shadow vs enforce) — the variant
  can observe/record without answering.

## 4. Compare + adopt

- Run the same suite against each variant; compare `benchmark` docs across
  runs (suite score, per-scenario status, durations — machine-readable meta).
- Adopt = keep the winning pointer, archive the loser unit. A policy-gate
  regression is an automatic reject regardless of score.
- Record the decision in the card that drove the change (comms + spec).

## 5. Memory transfer between personas

Banks are isolated by design (cross_instance_isolation is a gate). Selective
transfer — e.g. seed a variant with kk's car facts — is manual today:
export/import bank docs via MDDB. Tooling is a gap; card it when needed.
