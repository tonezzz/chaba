# Persona eval → variant → A/B → adopt — standard procedure

How to improve a persona (ada/kaewta/chaba/…) and prove it before shipping.
A persona = instance env + instructions + memory bank + model choice — there
is no weight training; "training" = iterating those four levers and measuring
with the scenario suite.

## 1. Measure the baseline

- Scenarios are yaml under ada-pi `tests/scenarios/` (unit-tier) and
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
- **Split A/B** (some senders → A, some → B): needs a per-caller override in
  the relay — card `persona-ab-lane` (OPS-0469). Until it lands, toggling +
  alternating test windows is the honest equivalent.
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
