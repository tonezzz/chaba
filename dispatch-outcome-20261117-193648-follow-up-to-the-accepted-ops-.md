# Dispatch outcome: render-jobs selective install (OPS-0790 follow-up)

Card: `render-jobs-selective-install-ops0790` (OPS-0993)

## State found

The `--ids` selector itself was already merged via the sibling reroute
card `render-jobs-selective-install-ops0790-tonydell` — commit
`7b5f86014d` (2026-11-07) added `render_host(man, host, ids)`, the
`timer_units()` `.timer`-suffix fix, unknown-id abort (rc 2), dispatcher
meta-unit exclusion under `--ids`, the `SelectiveInstall` test class (6
tests), and the scoped-rollout report. Baseline verified green:
22 tests OK, `--check` OK 106 jobs / 8 hosts.

## What this session added

The spec's "does not enable/restart unrelated timers" guarantee was only
proven at the *render* layer — the enable list derives from `units`, but
nothing exercised `main()`'s install path against a mocked systemctl.
A regression inside `main()` could have re-broken it silently.

- `tests/ops/test_render_jobs.py` — new `InstallPath` class (+5 tests,
  22 → 27): runs `main() --install` end-to-end with a synthetic
  `--manifest`, a fake `$HOME`, and mocked `subprocess.run`. Proves:
  - `enable --now` receives exactly `sel.timer`; unrelated units
    (`other.*`, `remote.*`) never appear in any systemctl argv; only the
    selected pair is written.
  - `chaba-jobs.{service,timer}` is neither written nor armed under
    `--ids` even while the host still has a dispatcher job — the
    rollout's keep-alive guarantee.
  - No-selector install still arms the full host set incl. the tick
    (full-host behavior preserved).
  - Unknown id → rc 2 before any write or systemctl call.
  - Ids matching no job on the host → zero systemctl calls (not even
    daemon-reload).
- `scripts/render-jobs.py` — fixed a latent bug found while building the
  tests: `--manifest` was parsed but `load_manifest()` ignored it
  (dead flag). `load_manifest(path=MANIFEST)` now honors it; all existing
  no-arg callers unchanged.
- `docs/reports/dispatcher-systemd-migration-2026-10-30-selective-install.md`
  — credited both cards, documented the `--manifest` fix and the new
  InstallPath coverage, refreshed counts (27 tests, 106 jobs / 8 hosts).

No live unit install, enable, start, or disable was performed — all
systemctl interaction is mocked in tests.

## Result

`python3 -m unittest tests.ops.test_render_jobs` → 27 tests OK.
`python3 -m unittest tests.ops.test_render_jobs tests.test_render_jobs_catalog`
→ 28 tests OK. `scripts/render-jobs.py --check` → OK 106 jobs, 8 hosts.

## How to verify

```
python3 -m unittest tests.ops.test_render_jobs.InstallPath -v   # 5 tests
python3 scripts/render-jobs.py --check                          # manifest valid
python3 scripts/render-jobs.py --host idc02 --ids bogus-id      # ERR rc=2
```

Rollout commands (per-host `--ids`) are in the report's "Scoped rollout
commands" section; `chaba-jobs.timer` stays active until all 8 migrated
timers verify.
