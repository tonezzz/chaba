# Dispatch outcome — timer-alert-idc03-ada-scenario-cms (2026-11-08)

## Result
Root cause found and the fix verified end-to-end on idc03: **deployment drift**, not a code bug or crash. Card comms updated; no repo changes needed.

## What actually happened
- The alert text ("last run 10-13 05:55") is the sentinel's stored body from October — it kept re-firing `[still suspicious]` because the unit's *latest* recorded result stayed `exit-code`.
- The real last run was **Tue 2026-11-03 05:55** (journal): the cms suite scored **0.0** — 5/5 scenarios failed, 4 of them with 0 turns/0s (sessions never opened).
- Why it exited 1 despite a completed run: idc03's deployed units + runner wrapper were **stale** — they predated both
  - the OPS-0581 contract (`timer-finding-reporter-semantics`, Oct 13): wrapper maps exit-1-with-`**Score:` to exit 0, and
  - `bench-off-paid-lanes` (Oct 15, commit `1c56115c5`): weekly suites target the FREE dev lane `:8005` behind a provider ExecCondition gate.
- The stale unit ran the suite against the **paid lane `ws://127.0.0.1:8002/ws` (ada-ha-tony)** during provider dunning — sessions failed to open (0 turns) — and the old wrapper exited rc=1. The sibling suites (research/memory/reports/tools) all show `result=exit-code` for the same reason.

## Fix state on idc03 (verified)
- `~/.local/share/ada-scenario-runner/scenario-suite-run.sh` was refreshed Nov 7 (partial — wrapper only), then a full `install.sh` ran **today 10:34** (concurrent actor — a sibling dispatch/runner-agent commented on `timer-alert-idc03-ada-scenario-memory` at 10:34:32).
- All 7 deployed unit files now **byte-identical (md5) to the repo copies**: dev lane `:8005`, `EnvironmentFile=ada-dev.env`, `ADA_KEYS_FILE`, `ExecCondition=scenario-provider-gate.py`.
- Verified by surface (OPS-0731): `systemctl --user start ada-scenario-cms.service` → provider gate reported `quota-dead — provider dunning in last 70min` → unit **skipped cleanly** (`Result=exec-condition`, status 0) — zero billed sessions, and `exec-condition` is not in the sentinel's alertable set (`failed|exit-code|timeout`), so the re-firing stops once `timer-timeline-idc03` refreshes.

## Residual / watch item
- The free-lane provider (ada-dev :8005) is currently **quota-dead** — the hourly smoke and the weekly suites will keep skipping by design until quota recovers. This is the gate working as intended (skip + `skip-quota` record + throttled `gate:quota-dead` chaba-event), not a failure. Next scheduled cms run: Tue 2026-11-10 05:55 +07.
- Nov 3's run did burn a handful of paid-lane sessions (cms_translate: 9 tool calls) before the paid-lane guard existed on the host — one-time, already prevented going forward.

## How to verify
```
ssh idc03 'systemctl --user show ada-scenario-cms.service -p Result --value'   # exec-condition (not exit-code)
ssh idc03 'md5sum ~/.config/systemd/user/ada-scenario-cms.service'            # d7e8ceea501c815bb493049cfd7e3898 == repo
ssh idc03 'journalctl --user -u ada-scenario-cms.service --since today --no-pager'
```
CMS `timer-timeline-idc03` should show the cms unit leaving `exit-code` after its next refresh.
