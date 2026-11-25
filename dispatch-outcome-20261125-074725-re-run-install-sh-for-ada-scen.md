# Dispatch outcome — idc03-re-run-ada-scenario-runner-install-a77c3c

## What was done

Re-ran `stacks/services/ada-scenario-runner/install.sh` on idc03 from the
exec checkout `~/CascadeProjects/chaba` (HEAD `b2a387c8`, contains the
lane-split commit `1c56115c5`). `podman build` used full cache
(image `localhost/ada-scenario-runner:latest` = `4494ce2aac4a`), all
quadlets/services/timers copied, `daemon-reload` + `enable --now` clean.

## Findings

- The card's core premise was already half-fixed: on 2026-11-24 21:39 a
  prior install had already pushed the :8005 dev-lane units
  (research/cms/reports) vs :8002 paid-lane (memory/tools/casting).
- One file had drifted since: `ada-scenario-smoke.container` — repo commit
  `9c58d304b3` (21:48, after that install) raised `TimeoutStartSec`
  2700→7800 and added `SCENARIO_BUDGET_S=7000`. The re-run converged it.

## Verified state on idc03 (post-install)

- Every file install.sh manages is byte-identical to repo HEAD (diff loop
  over all `ada-scenario-*`/`ada-spend-ledger`/`ada-bench-casting`/
  `ada-embed-bench` units + quadlets + `scenario-suite-run.sh` wrapper —
  zero DIFFERS).
- `ADA_LIVE_URL`: research/cms/reports = `ws://127.0.0.1:8005/ws`;
  memory/tools/casting = `ws://127.0.0.1:8002/ws` (by design).
- `ada-scenario-smoke.container`: `TimeoutStartSec=7800`,
  `SCENARIO_BUDGET_S=7000`.
- All 10 timers enabled; `ada-scenario-smoke.timer` active, next fire
  hourly; weekly suites armed (research Mon 05:55, cms Tue, reports Thu,
  memory Wed, tools Fri, casting Sat).
- Both lanes listening: :8005 (ada-dev) and :8002 (paid) uvicorn up.

## How to verify

```
ssh idc03 'grep ADA_LIVE_URL ~/.config/systemd/user/ada-scenario-*.service;
  systemctl --user list-timers | grep -E "scenario|bench|ledger"'
```

Expect :8005 on research/cms/reports, :8002 on memory/tools/casting.

lessons:
- Card premise can be stale: the :8005 lane split was already deployed
  11-24 21:39; always diff deployed units vs repo before assuming drift.
- install.sh is copy-on-install but NOT atomic with repo HEAD — a commit
  landing minutes after a run leaves quadlets stale (smoke.container
  TimeoutStartSec here). Re-running is cheap (podman cache hit).
- `systemctl --user list-timers` on idc03 shows NEXT/LAST per timer —
  good consumer-side proof the weekly suites are armed, not just enabled.
