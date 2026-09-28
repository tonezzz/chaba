# ada-scenario-runner

On-demand podman service that drives `tests/scenarios-live/*.yaml` through
`scripts/scenario-live.py` and writes one report doc per scenario into the
`ada-ha-scenario-reports` MDDB collection (outside the bank registry —
ops-only, never reachable via ada_memory_search).

## Tiers

- `smoke` — safe subset (`tier: smoke` in the yaml): connect/greet, memory
  read/write to own bank, ACL-deny probes. No actuation turns.
- `full` — everything including actuation scenarios. Manual only.
- `research` — weekly benchmark suite (`ada-scenario-research.timer`,
  Mon 03:30): runs `scripts/scenario-benchmark.py --suite research` from
  `tests/benchmark.yml`, scores pass/flaky/fail + audit-policy violations,
  writes one `kind: benchmark` doc to `ada-ha-scenario-reports` for trend
  tracking. Not a container — uses the repo venv directly.

Scenarios resolve `key_name:` against the mounted keys file; dict entries
with `device` also pass `device_id` (device-bound keys like user-kk).
A fail is retried once — pass-on-retry is recorded as `flaky`.

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
