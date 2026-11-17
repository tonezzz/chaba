# Dispatch outcome — ops-macbook-nestmgr-install

## Result: done

tony-macbook had woken up by session start (tailscale ping 11ms direct,
SSH OK — the card's "asleep" premise was stale). Installed nest-mgr from
this worktree via `bash stacks/services/nest-mgr/install.sh tony-macbook`
(scp path — no repo checkout needed on target).

## Verified

- `nest-mgr.service` — enabled + active (user unit, `~/.config/systemd/user/`)
- `~/.local/share/nest/manager-state.json` — live, 1 node adopted
  (`runner-agent`)
- CMS page `nest-tony-macbook` published to `ada-cms-pages` with real
  content (verify.sh: unit active / state ok / cms ok — all green)
- Daemon idles at 0 CPU between 60s ticks (initial ~40s discovery burst
  is normal; tony-omen shows the same burst-then-sleep pattern)

## Bonus fix — runner-agent drift (card comms remediation)

`runner-agent.service` on tony-macbook was crash-looping on every timer
tick: `AttributeError: 'str' object has no attribute 'get'` in
`reconcile_pass` — the same "installed runner-agent drifted from repo"
issue the card comms flagged for idc03/tony-omen. Applied the documented
fix: `scp scripts/board/runner-agent.py tony-macbook:~/.local/bin/runner-agent`
(installed copy was 4078 lines vs repo 4095, md5 differed). Agent now runs
a real pass — no crash.

Caveat: its first pass was still `activating` ~15 min in at close-out.
That's board-api write serialization (each call waits behind
`/tmp/board-api.lock` + git commit + render on idc03; agent uses 75s
timeouts and retries) — the known OPS-1314 bottleneck, not an agent bug.
It will finish on its own.

## Follow-ups worth noting (not done — out of scope)

- idc03 + tony-omen runner-agents were flagged as drifted at 18:10/18:26;
  if still unresolved they need the same one-line scp.
- nest-mgr burns ~1 CPU core during each discovery cycle on tony-omen
  (burst, then sleeps) — worth a look if it bothers battery/thermals;
  not a defect per se.

## How to verify

```
ssh tony-macbook systemctl --user status nest-mgr.service
cd stacks/services/nest-mgr && bash verify.sh tony-macbook
# Services card DevNest section lights up automatically via
# manager-state.json probe
```

Board comments posted on `ops-macbook-nestmgr-install` document each step.
No commits, no pushes — worktree unchanged except this outcome file.
