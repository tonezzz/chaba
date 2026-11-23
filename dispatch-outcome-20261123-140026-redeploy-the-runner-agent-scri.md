# Dispatch outcome — redeploy runner-agent on tony-dell + run flood monitoring (attempt 2)

Card: `req-47d7dd` (ติดตามสถานการณ์น้ำท่วม กทม. — continuous Bangkok flood
monitoring + traffic-route alerts). Claimed by this session on tony-dell
(dispatch `devin-task-20261123-140026-…`).

## What was found

- Attempt 1 (10:56 today, on tony-omen) had already completed this exact spec:
  scp'd the repo runner-agent to tony-dell, sha-verified `1e8ea0d8…`, ran
  flood-alert.service clean, posted DONE at 11:04. The card was re-queued at
  13:59 and claimed by tony-dell for this attempt.
- Pre-check on tony-dell at ~14:00 +07: all three copies already identical —
  `~/.local/bin/runner-agent` == `~/CascadeProjects/chaba/scripts/board/runner-agent.py`
  == this worktree's `scripts/board/runner-agent.py`, sha256 `1e8ea0d8…`.
  The last "tony-dell defers: installed runner-agent drifted" comms was
  2026-11-21 17:42; fleet convergence (sync-runner-tools / `_self_update`)
  healed it before either dispatch ran.

## What was done

1. `scp scripts/board/runner-agent.py tony-dell:~/.local/bin/runner-agent`
   per spec — landed byte-identical (sha256 `1e8ea0d8…` re-verified on host,
   exec bit preserved, fresh mtime 14:01).
2. Monitoring task = standing `flood-alert.timer` on tony-dell
   (`scripts/ada/flood-alert.py`, ssot.jobs.yml `job:flood-alert`, 15-min
   cadence, enabled+active). Executed a fresh manual run at 14:01:37:
   `Result=success`, `ExecMainStatus=0` — "3 items scanned, nothing new
   at/above warning (quiet x10)". Two upstream feeds returned HTTP 429
   (rate-limit, benign); run still succeeded.
3. Drift check: `journalctl --user -u runner-agent.service --since -24h |
   grep -i drift` → zero hits. The runner itself claimed this card at
   14:01:35 and is firing normally (last run 13:59, ~2min15s wall,
   Result=success); the only other gate observed is a separate card's
   attempt-cap refusal — unrelated.

## Result

Done-condition met: runner-agent redeployed to tony-dell via scp
(sha-verified identical to repo ref), and the continuous water-situation
monitoring task (armed `flood-alert.timer` + executed `flood-alert.service`
run) runs cleanly — no deployment drift errors.

## How to verify

```sh
ssh tony-dell 'sha256sum ~/.local/bin/runner-agent \
  ~/CascadeProjects/chaba/scripts/board/runner-agent.py'   # both 1e8ea0d8…
ssh tony-dell 'systemctl --user show flood-alert.service -p Result,ExecMainStatus;
  systemctl --user list-timers flood-alert.timer'
ssh tony-dell 'journalctl --user -u runner-agent.service --since -24h | grep -i drift'  # empty
```

lessons:
- Attempt 2 of a same-day redeploy card is usually re-verification, not re-work: check card comms for the prior attempt's DONE entry before repeating steps — the scp is idempotent so running it again is still correct and cheap.
- On the target host itself, `scp <file> tony-dell:~/.local/bin/...` works fine over the Tailscale name — no need to special-case localhost.
- flood-alert.service tolerates upstream feed 429s (logs warn, still exits 0) — partial feed failures are not a done-condition failure.
- The runner claiming the dispatch card you're executing under is itself positive proof the installed runner-agent is healthy — a claimed card means no drift defer fired.
