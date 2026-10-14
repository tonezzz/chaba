# ada-scenario-runner

On-demand podman service that drives `tests/scenarios-live/*.yaml` through
`scripts/scenario-live.py` and writes one report doc per scenario into the
`ada-ha-scenario-reports` MDDB collection (outside the bank registry —
ops-only, never reachable via ada_memory_search).

## Tiers

- `smoke` — safe subset (`tier: smoke` in the yaml): connect/greet, memory
  read/write to own bank, ACL-deny probes. No actuation turns. Hourly via
  `ada-scenario-smoke.timer` on **ada-dev (:8005, FREE key)**.
- `full` — everything including actuation scenarios. Manual only, and
  card-requested for the prod lane (see lane policy below).
- Weekly benchmark suites (`ada-scenario-{research,cms,memory,reports,
  tools,casting}.timer`, Mon–Sat 05:55): run
  `scripts/scenario-benchmark.py --suite <name>` from
  `tests/benchmark.yml`, score pass/flaky/fail + audit-policy violations,
  write one `kind: benchmark` doc to `ada-ha-scenario-reports` for trend
  tracking plus a `benchmark-<suite>` CMS page. Not containers — use the
  repo venv directly.
  - `research` / `cms` / `reports` target **ada-dev (:8005)** — they only
    need research/CMS/report tools the dev lane still exposes.
  - `memory` / `tools` / `casting` are lane-coupled (person-keyed banks,
    HA/actuation tool surface) and stay pointed at prod — parked by
    default per the lane policy below.
- `ada-bench-casting.timer` (daily 02:00) — preflight gate; on success
  chains into `ada-scenario-casting.service` via `OnSuccess`.

## Lane policy — automated probes never bill a paid project

(card `bench-off-paid-lanes`, 2026-10-14) Prod persona lanes —
ada-ha-tony :8002, ada-ha-michael :8003, ada-kk :8007, ada-pi-pwa :8001 —
each bill a per-persona **paid** Gemini key; the dev lanes
(ada-dev :8005, ada-kk-dev :8009) ride the FREE key. Two controls keep
scheduled traffic off the paid keys:

1. **`scenario-provider-gate.py` ExecCondition** on every suite —
   sha-compares the target unit's `GEMINI_API_KEY` against
   `gemini-keys.env`; a PAID (or unmarked) key fails the run before a
   single session opens, and quota-dead providers are skipped too.
2. **Paid-lane guard in `scenario-suite-run.sh`** — the wrapper checks
   `ADA_LIVE_URL`'s port: :8005/:8009 proceed, anything else is treated
   as paid and the run parks (`exit 0`, zero sessions, journal trail).

**Card-requested prod runs** (the release s4/s5 gate — the only path
allowed to touch a prod lane): authorize one run with a one-shot
sentinel, then start the unit:

```bash
echo <card-id> > ~/.local/share/ada-scenario-runner/prod-allow-<suite>
systemctl --user start ada-scenario-<suite>   # consumes the sentinel
```

The gate honors a sentinel for up to 7 days (`--paid-allow-max-age`) and
still refuses when the provider is quota-dead. `ada-scenario-full` uses
`prod-allow-full` the same way. Known footgun: `scenario-report.py`
honors a per-scenario `url:` override — a yaml hardcoding a paid ws URL
bypasses `ADA_LIVE_URL`; keep `url:` fields off paid lanes in smoke/weekly
scenarios.

Canary probes live in `stacks/services/ada-live-canary/` — free key
hourly, paid key **once daily** (1 connect/day detects dunning).

## Scheduling / locking

Suites share one Ada session and the vcast screens, so exactly one may
run at a time. The suite-level lock is a TCP bind+listen on
`127.0.0.1:8199` (works across the host-network smoke container); the
per-scenario driver uses :8198.

- `scenario-report.py` (smoke tiers) skips cleanly when :8199 is held.
- `scenario-benchmark.py` (weekly suites) refuses with exit 2 — the
  weekly services therefore run through `scenario-suite-run.sh`, which
  waits up to 30 min for :8199 to become bindable and re-queues on a
  lost bind race, so a transient holder delays instead of dropping the
  run. Probe = actual bind (connect-probes are unreliable against the
  backlog-1 listener). The wrapper also normalizes the benchmark's
  exit-1-on-failures to the timer exit-code contract (exit 0 on a
  completed run — detected via the `**Score:` final-report marker);
  findings live in `ada-ha-scenario-reports` + the `auto-report` page
  (docs/kb/timer-expectations.md).
- Weekly slots sit at `:55` — past the smoke worst case (`:00` start +
  45 min `TimeoutStartSec` + kill margin ≈ `:47`) and past the daily
  casting chain (`02:00` + 2 h cap = free by `04:00`). A suite that
  grabs the lock before the next `:00` makes that hour's smoke skip,
  which is the correct priority order.

History: pre-2026-10-09 the weekly timers fired at 03:30 — inside both
the smoke window (03:00→~03:35) and the hung daily casting run
(02:00→04:00), so every weekly was refused. Card
`fix-scenario-schedule-collision`.

Scenarios resolve `key_name:` against the mounted keys file; dict entries
with `device` also pass `device_id` (device-bound keys like user-kk).
A fail is retried once — pass-on-retry is recorded as `flaky`.

Statuses: `pass` / `flaky` / `fail` / `skip` (missing key) / `quota`
(upstream throttle seen in output) / `infra` (backend unreachable —
connect refused, no ready event) / `skip-quota` (outage sentinel tripped
— 2 consecutive quota/infra results skip the rest of the tier; none of
these fail the unit).

## Spend guard (card scenario-spend-guard)

`ada-scenario-smoke.service` carries
`ExecCondition=…/chaba/scripts/ada/scenario-provider-gate.py` — a
zero-spend probe (journald + env-file reads only, no API call) that runs
once per scheduled fire before the container starts:

- **unit down** → skip (status `infra`)
- **live key is the PAID lane while `gemini-keys.env` marks a FREE
  lane** → skip (`skip-quota`) — the "never the paid key while a free
  lane exists" rule, enforced by sha-compare (no key material logged)
- **quota-dead** — `provider (re)connect failed` / `exceeded your
  current quota` / `1011` / `RESOURCE_EXHAUSTED` in the last 70 min with
  no newer healthy marker → skip (`skip-quota`)

A gated run still lands in lab-results: the gate writes one
`report/<scenario>-<ts>` skip doc per smoke scenario plus a
`report/smoke-gate-<ts>` summary, so the skip is reported, not silent.
It also runs the **reconnect-churn counter** every fire: >50 ws
`client connected`/hour on an `ada-ha-*` unit emits a throttled warn to
chaba-events (retry storms are the other quota burner).

`ada-spend-ledger.timer` (daily 23:50) + a best-effort `ExecStopPost`
after each smoke run → `scripts/ada/spend-ledger.py`: per-day Live
sessions / turns / aux calls / tokens / est $ from the backend's own
`data/usage.jsonl` plus per-unit ws churn from journald, published to
the `spend-ledger` CMS page (`domain: ops` → shows in ops-digest) and
`report/spend-<date>` snapshot docs.

Dev lane: a scenario can set `url: ws://127.0.0.1:8005/ws` to run against
`ada-dev` (isolated instance — `dev-*` banks only, no HA tools, admin key
only). Suitable for dispatch/bench/lab-write experiments, NOT for
memory-recall or person-keyed scenarios.

## Install (on the Ada host)

```bash
cd stacks/services/ada-scenario-runner && ./install.sh
```

## Run

```bash
systemctl --user start ada-scenario-smoke   # or ada-scenario-full
journalctl --user -u ada-scenario-smoke -f
```

Reports: `ada-ha-scenario-reports` collection, `report/<name>-<ts>`,
meta `{status: pass|fail|flaky, valid_until: +14d}`.
