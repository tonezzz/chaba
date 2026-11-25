# Dispatch outcome — redeploy drifted runner-agent (logs-digest-program)

## Result: already converged — no redeploy needed

Verified sha256 of both `~/.local/bin/runner-agent` and
`/home/tony/CascadeProjects/chaba/scripts/board/runner-agent.py` on every
target host. All four are byte-identical:

- idc03, idc02, tony-dell (via ssh) and tony-macbook (this session runs on
  the host itself; `tony-macbook` resolves to 127.0.1.1, ssh-to-self fails
  by design — checked locally instead).
- Hash everywhere: `1514c75c4679a01b486bbffd9f75c5636d023fed528424aed358a970ee3f7210`
  — matches the worktree's `scripts/board/runner-agent.py` too.

Drift was already healed by `runner-agent._self_update()` /
`sync-runner-tools.sh` before this dispatch landed (consistent with the
KNOWN_PITFALLS note that drift-defer cards are often already clean).

## Execution verification (done-condition)

`runner-agent.service` runs under a user timer on each host. Last 24h of
journals show clean pass cycles (`Finished runner-agent.service` every
~1min) with **no** `drift`/`self_stale`/traceback errors on any host —
only unrelated warns (lesson-bank write timeouts, board-api claim
lock-saturation retries, runner-at-cap skips). `runner-agent.timer`
active on tony-macbook, idc02, tony-dell; idc03 timer active with service
between passes. A prior dispatch of this same goal ran on idc02 at
15:47 today (`devin-task-20261125-154725-redeploy-the-drifted-runner-ag`)
— likely the cycle that converged the fleet.

## Files changed

None — `cp` would have been a byte-no-op. Card comms posted to
`logs-digest-program` documenting the verification.

## How to verify

```
ssh <host> 'sha256sum ~/.local/bin/runner-agent \
  /home/tony/CascadeProjects/chaba/scripts/board/runner-agent.py'
journalctl --user -u runner-agent.service --since "24 hours ago" | grep -i drift
```

## lessons:

- `tony-macbook` resolves to 127.0.1.1 — dispatches landing there must
  check files locally; ssh-to-self is denied (no self key).
- Drift-defer redeploy cards keep arriving already-healed; sha256 BOTH
  paths on every host before any `cp` — this was the 4th+ occurrence.
- idc02's journal shows a prior dispatch of this exact goal at 15:47 —
  duplicate dispatches for the same drift card can race; check card
  comms for a same-day "redeploy" attempt before re-verifying.
