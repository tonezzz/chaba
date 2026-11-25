# Dispatch outcome — idc02-audit-census-reconcile (2026-11-25)

## Result

`python3 scripts/audit-hosts.py --host idc02` → **"No deltas against SSOT
expected state."** (was 28 deltas). `audit-hosts.py --host mn01` verified
the same-day mn-ha-dev move landed in census — only residual is
`yolo-xiaomi.service` missing (honest drift, carded as AUD-1396).

## What changed (worktree, uncommitted — dispatcher merges)

- `docs/ssot/infrastructure/ssot.audit.hosts.yml`
  - **idc02 expected_absent +=** mn-ha-dev.service + mha-state-push.service
    (moved to mn01 2026-11-25 ~08:20, commit 5a0601d3 — the migrate commit
    never touched this file), camwall-render-check.timer (retired in
    camwall-retire-to-wiki Phase 2, Tony-approved ada-snapshot-only),
    vcast-real-macbook.service (named unit never existed on idc02;
    superseded by vcast-real@6/@7), all six retired ada-code/jack quadlet
    units, mddb-lab-pull.timer (masked wind-down).
  - **idc02 expected_services +=** gesture-relay, gpu-queue,
    gpu-queue-processor, weaviate, web, opencode-serve, ollama, mddb-lab —
    the OPS-0725/0731 migration adds the card described.
  - `type: service → oneshot` on runner-agent.service,
    kanban-dispatch.service, openchamber-update.service; ada-stt.service →
    `expected_state: inactive` (disabled parked lane).
  - **idc02 known_failed +=** ada-ocb-eval, ada-ocb-smoke,
    ada-ocb-agent-runner-converge, fleet-restic-backup, kk-mac-model-status,
    mddb-backup, wp-backup-pull — each reason cites its existing
    timer-alert-idc02-* tracking card (benchmark-fail and orphaned-job
    signals are not host drift).
  - **mn01**: expected_services += mn-ha-dev.service (critical) +
    mha-state-push.service (verified active via ssh); expected_absent +=
    vcast-real-macbook.service; known_failed += mn01-canary.service.
- `scripts/audit-hosts.py`
  - `linux_services()` now probes `systemctl [--user] list-unit-files`
    into `observed.unit_files_{user,system}`.
  - New census kind `type: oneshot`: expected_state:active oneshots diff
    on unit-file presence (masked = absent) instead of active listing.
    Chose this over `list-units --all` because --all still reports
    masked/inactive units as present — it would have hidden the mn-ha-dev
    mask drift. Probe-absent (macOS) falls back to legacy path.
- `docs/ssot/jobs/infrastructure/2026-11-25-idc02-audit-census-reconcile.yml`
  — full job trail.

## Live fixes applied on idc02 (reversible, restored declared state)

- `systemctl --user start mddb-embed.service` — was down ~30h since the
  2026-11-24 09:20 reboot; quadlet lacks `[Install] WantedBy=` so it never
  auto-starts. Now active, `/v1/health` = healthy, :11028 listening.
- `systemctl --user start gev-cmd-relay.service` — dead since same boot
  (BindsTo dependency race); now active.
- `systemctl --user stop ada-code-network.service jack-ide-network.service`
  — stale generated units still ACTIVE after quadlet retirement;
  daemon-reload alone did not clear them.
- `systemctl --user reset-failed mddb-lab-pull.timer` — masked+failed
  state cleared for expected_absent.

## Findings carded / posted

- AUD-1396 `mn01-yolo-xiaomi-service-stopped-deliber-d2b384` — yolo-xiaomi
  SIGTERM'd 02:38 UTC during the migration window; restart-vs-park is a
  decision, not guessed.
- Root cause posted on timer-alert-idc02-ada-ocb-agent-runner-converge:
  unit sets `User=tony` inside a `--user` unit → exit 216/GROUP.
- timer-alert-idc02-camwall-render-check is now answered (deliberate
  retirement) — its "disabled but expected active" note is resolved by
  this census.

## Verify

```
python3 scripts/audit-hosts.py --host idc02   # -> No deltas
python3 scripts/audit-hosts.py --host mn01    # -> only yolo-xiaomi missing
systemctl --user is-active mddb-embed gev-cmd-relay   # -> active active
curl -s http://100.123.163.11:11028/v1/health          # -> healthy
```

## Residuals / follow-ups

- mddb-embed.container still lacks `[Install] WantedBy=default.target` —
  will not survive next reboot (host-local file, not repo-managed; noted
  in SSOT entry).
- Unused podman bridges `ada-code`, `jack-ide` remain after retirement.
- vcast-real-macbook.service stale declaration also sits in tony-omen /
  macbook / idc03 census sections — same 11-12 fleet-wide copy.
- mn01-canary 11-25 03:30 reported "idc03 ada services 1/3 active" — real
  signal tracked by timer-alert-mn01-mn01-canary.
- Undeclared *timers* on idc02 (ada-ocb-*, fleet-restic-backup,
  wp-backup-pull, embed-lane-banks, etc.) produce no audit deltas — the
  unexpected-running check only covers `.service`; possible follow-up to
  extend census coverage to timers.

lessons:
- `systemctl list-units` (no --all) shows only active+failed units; `list-units --all` adds loaded-inactive but ALSO masked units — for "is it supposed to run" probes use `list-unit-files` (name->state), never --all.
- Quadlet-generated `.network` units can stay ACTIVE=exited after their `.network` file is retired — daemon-reload does NOT clear them; explicit `systemctl --user stop` does.
- The 2026-11-25 mn-ha-dev idc02->mn01 migrate commit repointed "all SSOT refs" but missed ssot.audit.hosts.yml entirely — service migrations must include the audit census on BOTH source (expected_absent) and destination (expected_services) hosts.
- Benchmark/oneshot services that exit nonzero on FAIL (ada-ocb-eval/smoke) belong in known_failed with the timer-alert card ref — the failed state IS their signal channel, not host drift.
- Orphaned unit check: `systemctl --user is-enabled` + `cat` ExecStart vs repo — kk-mac-model-status pointed at a script that never existed in the repo.
