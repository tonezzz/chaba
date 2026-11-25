# Dispatch outcome — redeploy drifted runner-agent (idc02 + tony-dell)

Card: `gdrive-ada-nest-pack-catalog-retention-p-e0d183`
Date: 2026-11-25

## Result: done-condition already met — verified, no redeploy needed

The drift the card describes was healed before this dispatch ran. On
both target hosts, `~/.local/bin/runner-agent` and
`~/CascadeProjects/chaba/scripts/board/runner-agent.py` are
byte-identical (sha256
`1514c75c4679a01b486bbffd9f75c5636d023fed528424aed358a970ee3f7210`),
matching origin/master's `scripts/board/runner-agent.py` AND the
`runner_agent` pin in `scripts/devin/runner-tooling.manifest.json`.
Installed snapshots were refreshed at 15:42 +07 today (~5 min before
this card was claimed at 15:47) via the governed path —
`sync-runner-tools.sh` at the `git-safe-pull` tail / `_self_update()`.
A manual copy would have been a byte-no-op, so none was performed.

## Verification evidence

- **idc02**: service exits 0/SUCCESS every ~60s; claimed this very
  card at 15:47:46 (this session is the consumer proof); zero
  "drifted from repo" events in 24h journal.
- **tony-dell**: service cycling cleanly (~75s cadence, exits
  normally); claimed `mn-ha-dev-crash-looped-40x` card at 15:47:35;
  zero drift events in 24h journal.
- **Fleet sweep** (read-only sha256): idc03, mn01, tony-omen,
  tony-macbook, con01 all CONVERGED to the same triple-match.

## Context

`runner-agent.py` last changed in `e46eb5847b` (2026-11-25 12:33
+07). Drift defers in card comms through 07:50 were the known
transient window: chaba-repo-sync pulls updated the checkout copy
(12:43–13:00) before the tool-sync installed the snapshot (15:42), so
`_self_stale_check`'s byte-compare reported drift in between. The
governed convergence healed it within one sync cycle, as designed.

## Deliverables

- Trail: `docs/ssot/jobs/board/2026-11-25-runner-agent-drift-redeploy-verify.yml`
  (committed on dispatch branch `dispatch/20261125-154725-redeploy-the-drifted-runner-ag`,
  commit fb84b87499)
- Card comms posted with the same summary.

## How to verify

```
ssh idc02 'sha256sum ~/.local/bin/runner-agent ~/CascadeProjects/chaba/scripts/board/runner-agent.py'
ssh tony-dell 'sha256sum ~/.local/bin/runner-agent ~/CascadeProjects/chaba/scripts/board/runner-agent.py'
# both should print 1514c75c4679a01b486bbffd9f75c5636d023fed528424aed358a970ee3f7210 twice
systemctl --user status runner-agent.service   # on each host
```

lessons:
- Drift-defer cards are often already healed by the time a dispatch lands — sha256 BOTH `~/.local/bin/runner-agent` and `<checkout>/scripts/board/runner-agent.py` before touching anything; a manual cp is a byte-no-op on converged hosts.
- Transient drift window = repo-sync pull lands new runner-agent.py before sync-runner-tools/_self_update installs it; expect flap, not persistent drift, after any runner-agent.py commit.
