# Selective `--install` for rendered timers (OPS-0993)

Date: 2026-10-30 · Card: `render-jobs-selective-install-ops0790-tonydell` ·
Parent: `dispatcher-systemd-migration-2026-10-29` (OPS-0790)

Code/tests only — no live unit install, enable, start, or disable.

## Problem

`render-jobs.py --host <h> --install` writes every rendered unit for that
host and then runs `systemctl --user enable --now` over **all** of them.
For the approved host-by-host OPS-0790 rollout that would arm unrelated
timers (retriggering unrelated jobs and spend) instead of only the eight
migrated dispatcher jobs.

A second latent bug surfaced while verifying: the enable list stripped the
`.timer` suffix (`n[:-6]`), so `enable --now <name>` resolved to the
**.service** — which is `static` (no `[Install]`), fails enable, and got
started once by `--now`. The old command never actually armed a timer.

## Change (`scripts/render-jobs.py`)

- New `--ids <csv>` selector. `render_host(man, host, ids)` emits only the
  selected jobs' `<id>.service`/`<id>.timer` pairs, so the install path can
  only write/enable those units. No `--ids` → unchanged full-host render.
- `chaba-jobs.{service,timer}` are excluded under `--ids`: dispatcher
  meta-units are not per-job selectable, and the rollout keeps the tick
  alive until all eight migrated timers are verified.
- Unknown ids abort with `ERR` + rc 2 before any write/systemctl call —
  a typo must fail, not silently install nothing.
- A host that matches no selected id prints `<host>: no units match --ids`
  instead of silently skipping.
- `timer_units(units)` keeps the `.timer` suffix for `enable --now`
  (fixes the never-armed-timer bug above).

## Scoped rollout commands

Only the eight migrated jobs, per host:

```
python3 scripts/render-jobs.py --host idc03 \
    --ids embed-lane-news,embed-lane-lessons,yomi-update-active --install
python3 scripts/render-jobs.py --host idc02 \
    --ids embed-lane-banks --install
python3 scripts/render-jobs.py --host tony_dell \
    --ids mcp-debug-h3-sync,tony-dell-health-snapshot,network-scan-tony,lesson-drift-check \
    --install
```

Then per job: `systemctl --user list-timers <id>.timer` plus one forced
`systemctl --user start <id>.service` to verify — same as the original
rollout plan. `chaba-jobs.timer` stays active until all eight pass, then
the disable/cleanup step in the parent report applies.

## Tests (`tests/ops/test_render_jobs.py`, +6 → 22 total)

- `--ids` render on `tony_dell` returns exactly the selected pairs.
- No unrelated `*.timer` appears in a selective render (the enable input
  is derived from `units`, so an extra timer name is an armed extra job).
- `chaba-jobs.*` never emitted under `--ids`, still emitted unfiltered.
- `ids=None` is byte-identical to the unfiltered render.
- Ids from another host render nothing (and the CLI reports the miss).
- `timer_units()` keeps the `.timer` suffix (enable targets timers, not
  static services).
- Incidental: the pre-existing `GeneratedTree` drift was caught while
  running this suite — 5 manifest jobs lacked committed units; re-rendered
  (`devnest-capacity-broker`, `devnest-report-feed`,
  `jevnest-kk-mac-capacity-producer` on tony_dell; `cline-board-mirror` on
  con01). The guard is green again.

## Verification

```
python3 -m unittest tests.ops.test_render_jobs   # 22 tests OK
python3 scripts/render-jobs.py --check           # OK 92 jobs, 8 hosts
python3 scripts/render-jobs.py --host tony_dell --ids bad-id
# ERR unknown job ids: bad-id  (rc=2, no writes, no systemctl)
```
