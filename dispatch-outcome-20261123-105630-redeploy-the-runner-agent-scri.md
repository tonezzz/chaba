# Dispatch outcome — redeploy runner-agent on tony-dell + run flood monitoring

Card: `req-47d7dd` (ติดตามสถานการณ์น้ำท่วม กทม. — continuous Bangkok flood
monitoring + traffic-route alerts). Claimed by this session on tony-omen.

## What was found

- **The tony-dell drift was already healed before this session.** Live state
  on tony-dell at ~10:58 +07:
  - `~/.local/bin/runner-agent` sha256 `1e8ea0d8…` == `~/CascadeProjects/chaba/scripts/board/runner-agent.py`
    sha256 `1e8ea0d8…` == this worktree's copy at `a84dab8234` (origin/master tip).
    The last "tony-dell defers: installed runner-agent drifted" comms was
    2026-11-21 17:42; the fleet convergence (sync-runner-tools / self-update)
    had since closed it.
  - `runner-agent.timer` enabled, firing ~every 2.7 min; `runner-agent.service`
    `Result=success` and actively claiming (`ada-prompt-slim` claimed at 10:53).
  - `flood-alert.timer` enabled, every 15m — the standing "continuous water
    situation monitoring" job on tony_dell (`scripts/ada/flood-alert.py`,
    ssot.jobs.yml `job:flood-alert`); its home-page feed already scores
    traffic items (ท่วมขัง/ถนนปิด) at warning.
- `req-47d7dd` itself is `action.status: running` under the `tony-omen`
  claim (this session) — a re-queue to tony-dell is refused while running
  and would only respawn the same meta-spec; the card IS the monitoring ask,
  not a second task to enqueue.

## What was done

1. `scp scripts/board/runner-agent.py tony-dell:~/.local/bin/runner-agent`
   per spec — landed byte-identical (sha256 `1e8ea0d8…` verified on the host
   against both copies; exec bit preserved, mtime 11:02).
2. Executed the monitoring task on tony-dell:
   `systemctl --user start flood-alert.service` → `Result=success`,
   `ExecMainStatus=0`, "5 items scanned, nothing new at/above warning
   (quiet x64)" at 11:02:49.
3. Ran a post-scp runner claim pass on tony-dell (11:04) →
   `Result=success`; the only gate was load capacity ("script claims
   only", 5m load/core 1.32 > 0.85) — **no drift defers**.
   `journalctl --since -24h | grep -i drift` on tony-dell: zero hits.

## Result

Done-condition met: runner-agent updated on tony-dell via scp
(sha-verified), and the continuous water-situation monitoring task
(flood-alert.service) executes cleanly — no deployment drift errors.

## How to verify

```sh
ssh tony-dell 'sha256sum ~/.local/bin/runner-agent \
  ~/CascadeProjects/chaba/scripts/board/runner-agent.py'   # both 1e8ea0d8…
ssh tony-dell 'systemctl --user show flood-alert.service -p Result,ExecMainStatus;
  systemctl --user list-timers flood-alert.timer runner-agent.timer'
ssh tony-dell 'journalctl --user -u runner-agent.service --since -24h | grep -i drift'  # empty
```

lessons:
- Check `sha256sum` of BOTH `~/.local/bin/runner-agent` and `<exec checkout>/scripts/board/runner-agent.py` on the target host before assuming drift — sync-runner-tools.sh / `_self_update` may have already healed it (tony-dell was clean today despite yesterday's defer comms).
- The runner posts "defers: installed runner-agent drifted" on EVERY card it scans while stale (claim_pass checks `self_stale_reason` even for non-queued cards) — defer spam on a card does not mean that card was ever queued.
- A card `running` under a dispatch claim cannot be re-queued (`/action do=queue` → "already running"); "queue the task" for the standing flood monitor means the armed `flood-alert.timer` + a triggered `flood-alert.service` run, not re-arming the card itself.
- tony-dell runner gates heavy claims at 5m load/core > 0.85 ("script claims only") — a non-drift capacity gate; do not misread it as the drift problem persisting.
