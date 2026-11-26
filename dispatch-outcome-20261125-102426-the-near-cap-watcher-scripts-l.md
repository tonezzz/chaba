# Dispatch outcome — litellm-budget-watch-enable

Card: `litellm-budget-watch-enable` (ref OPS-1360 / SEC-0962)
Date: 2026-11-25 · Host worktree: idc02 · Target host: idc03

## What changed

- `docs/ssot/infrastructure/ssot.jobs.yml` — declared job
  `litellm-budget-watch` (host idc03, `dispatch: systemd`, `every: 1h`,
  `persistent: true`, `timeout: 5m`,
  `exec: /usr/bin/python3 %h/CascadeProjects/chaba/scripts/litellm/budget-watch.py`,
  `cwd` + `env_file: %h/.config/secrets/litellm.env` (LITELLM_MASTER_KEY
  for the /key/list fallback), `condition_path` on the script).
- `systemd/generated/idc03/litellm-budget-watch.{service,timer}` —
  rendered via `python3 scripts/render-jobs.py --host idc03`
  (OnBootSec=1min + OnUnitActiveSec=60min, Persistent).
- `docs/ssot/jobs/infrastructure/2026-11-25-litellm-budget-watch-timer.yml`
  — job trail (decision + verification).
- Installed live on idc03: scp'd both units to
  `~/.config/systemd/user/`, `daemon-reload`, `enable --now
  litellm-budget-watch.timer`. Done out-of-band because the declaring
  commit isn't on idc03's exec checkout yet; content is identical to
  what `render-jobs.py --host idc03 --ids litellm-budget-watch --install`
  would write, so a later install is a no-op.

## Result — DONE condition met

- Timer installed and active on idc03; it fired immediately on enable
  (OnBootSec catch-up): service exited 0/SUCCESS, read
  `postgres:VerificationToken` via `podman exec litellm-db psql`,
  verdict ok (0 alerts / 0 warns across all keys), LINE n/a (verdict
  ok), ops-event emitted to `ada-ha-events-tony`.
- `ssh idc03 'python3 scripts/litellm/budget-watch.py --selftest'` →
  selftest OK (bench alert, chaba warn, ada/mddb ok, uncapped note).
- `ssh idc03 'python3 scripts/litellm/budget-watch.py --dry-run'` →
  live psql read, verdict ok, `ops-event: dry-run`.
- `python3 -m unittest tests.litellm.test_budget_watch` → 13 tests OK.
- `render-jobs.py --check` → OK 126 jobs, 8 hosts; generated diff is
  exactly the two new unit files.

Cadence rationale: hourly (not key-watch's 6h) because spend can move
fast during eval burns; the psql read is one cheap query and LINE noise
is bounded by the script's 240-min resend dedup + 00-07 ICT quiet
deferral. At ≥100% calls are already 422ing — the ≥80% warn is the
advance-notice layer this timer exists to surface.

## How to verify

```
ssh idc03 'systemctl --user list-timers litellm-budget-watch.timer'
ssh idc03 'systemctl --user status litellm-budget-watch.service'
ssh idc03 'journalctl --user -u litellm-budget-watch.service -n 20'
ssh idc03 'cd ~/CascadeProjects/chaba && python3 scripts/litellm/budget-watch.py --selftest'
```

Next scheduled run: hourly (OnUnitActiveSec=60min from last activation).

## Lessons

- `systemctl --user list-timers` over BatchMode ssh works on idc03 —
  no need for a loginctl/linger dance for user timers there.
- render-jobs `--install` writes to the *local* host's
  `~/.config/systemd/user`; for a remote target, scp the generated
  units + `daemon-reload` + `enable --now <id>.timer` (keep the .timer
  suffix — bare names resolve to .service).
- The litellm.env secrets file on idc03 carries `LITELLM_MASTER_KEY`
  plus DB creds — safe to attach as the job `env_file` for the API
  fallback path.
