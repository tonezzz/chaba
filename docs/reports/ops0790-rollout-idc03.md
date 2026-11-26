# OPS-0790 rollout note — idc03 (reconstructed)

> **Provenance:** this note was required by card `ops0790-rollout-idc03`
> spec step (4) but was never committed — the rollout itself was executed
> 2026-11-07 via direct ssh (dispatch was stuck queued) and closed by Tony
> the same day. Reconstructed 2026-11-25 from the card's DONE comms and
> `docs/ssot/infrastructure/ssot.jobs.yml` under audit card
> `audit-miss-claimed-docs-never-landed`. Treat timestamps below as the
> recorded comms values, not re-verified live state.

Card: `ops0790-rollout-idc03` (parent OPS-0790 / OPS-0983 dispatcher→systemd
migration; selective-install code landed via `render-jobs-selective-install-ops0790-tonydell`,
see `docs/reports/dispatcher-systemd-migration-2026-10-30-selective-install.md`).

## What ran

Host: **idc03**, worktree at `origin/master` (prereq ≥ `7b5f86014`).

```
python3 scripts/render-jobs.py --host idc03 \
    --ids embed-lane-news,embed-lane-lessons,yomi-update-active --install
```

`--install` wrote only those three `<id>.service`/`<id>.timer` pairs to
`~/.config/systemd/user`, ran `daemon-reload`, and `enable --now`'d exactly
those three `.timer` units. No other units touched; `chaba-jobs.timer`
stayed armed; no package installs.

## Per-job result (from card comms, 2026-11-07 15:52)

| job | timer armed | forced first run (`systemctl --user start <id>.service`) |
|---|---|---|
| `embed-lane-news` (news title vectors, nomic, every 1h) | yes — verified via `list-timers` | ran to **success** |
| `embed-lane-lessons` (lesson CPT vectors, nomic, every 1d) | yes — verified via `list-timers` | left **running** (real job, not a failure) |
| `yomi-update-active` (Yomi active-conversation update, every 15m) | yes — verified via `list-timers` | left **running** (real job, not a failure) |

Per the rollout spec, a job still running at check time is data, not a
blocker — the timers stayed armed.

## Follow-ups

- The card sat `done` but kept attracting dispatcher `defers` noise for
  ~3 weeks (labels/`exec` capability mismatch — see card
  `dispatch-claim-eligibility-visibility` and job doc
  `docs/ssot/jobs/kanban/2026-11-08-dispatch-claim-eligibility-visibility.yml`).
- Sibling rollouts: `ops0790-rollout-idc02` (embed-lane-banks),
  `ops0790-rollout-tony-dell` (mcp-debug-h3-sync,
  tony-dell-health-snapshot, network-scan-tony, lesson-drift-check).
- Parent close-out: once all eight migrated timers verified, the
  `chaba-jobs.timer` disable/cleanup step in the migration report applies.
