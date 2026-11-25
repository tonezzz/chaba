# Dispatch outcome — stagger-idc03-timer-herd (2026-11-25)

## What changed

- `docs/ssot/infrastructure/ssot.jobs.yml`: applied fixed-minute offsets to every
  idc03 `dispatch: systemd` job that used `on_calendar`, eliminating the
  `:00`/`:30` wall-clock herd. `*:0/30` jobs got distinct `/30` residues
  (`:04`, `:06`, `:16`, `:19`, `:26`), `hourly`/`daily` were pinned to fixed
  minutes (`:08`, `:18`, `:31`, `:38`, `:48`, `00:14`), and fixed times moved a
  few minutes off the herd (`02:09`, `03:13`, `04:03/18/33/48`, `05:19`, `06:09`,
  `07:01/31/36/41/46`, `08:06`, `08:34`, `10:39`, `13:23→:23` cadence kept).
  Jobs already off-`:00/:30` (daily-brief `:05`, qc `:20`, deploy-preflight
  `*:07/5`, board-invariants `:35`, kraut-rain `:11/:41`, education-report `:50`,
  wp-news-situation `:45`) were left alone. A `schedule:` conventions note now
  documents the "free residue" rule for future jobs.
- `systemd/generated/idc03/*.timer`: 32 timer files regenerated
  (`render-jobs.py --check` → `OK 125 jobs, 8 hosts`; every new OnCalendar
  string passes `systemd-analyze calendar`).
- Installed on idc03 `~/.config/systemd/user/`: 29 pre-existing timer units
  updated + `daemon-reload` + restart. `wiki-talk-watch.timer` and
  `wp-news-morning-brief.timer` were **not** installed — they were never
  installed before, and wiki-talk-watch's own manifest note says
  "render-jobs.py --host idc03 --ids wiki-talk-watch --install **after
  merge**". Both scripts + secrets exist on idc03, so a post-merge
  `render-jobs.py --host idc03 --install` will pick them up.
- `runner-agent` redeployed: `scp scripts/board/runner-agent.py
  idc03:~/.local/bin/runner-agent` (chmod 0755). sha256 verified identical
  across worktree copy, idc03 exec checkout, and installed bin:
  `0bc62e20bab2552b5f757c73fccaed03d8bc148e6a81c41b8764d57225472e92`.
  runner-agent.timer fires every 60s and the new binary is running clean
  claim passes (it self-throttles under load — "host overloaded" skips).

## Incident during install (important)

Restarting the 29 timers at 09:57 triggered a **one-time `Persistent=true`
catch-up wave**: systemd treated the restart gap as missed elapses and fired
~24 services simultaneously on a 4-core host (load peaked ~37). Effects:

- Stopped the still-running catch-up services at ~09:59 (`systemctl --user
  stop` on overnight-assessment, focus-dispatcher-overnight, chaba-kanban-brief,
  chaba-unattended-report, chaba-tony-ideas, kanban-sync,
  chaba-bge-education-shadow, ada-transcript-archive) so real schedules would
  fire on a quiet host. They show `result=signal` and will rerun normally.
- The wave exposed two real bugs (carded below) and wedged board-api.
- board-api held `/tmp/board-api.lock` + `/tmp/board-api-wp.lock` while an
  outbound HTTPS call to 103.99.11.249:443 hung ~8 min; all endpoints timed
  out. Restarted `chaba-board-api.service` at 10:07 — recovered immediately.

## Verification

- `render-jobs.py --check`: OK 125 jobs, 8 hosts.
- Installed unit files `cmp`-verified identical to worktree generated files.
- `systemctl --user list-timers`: next elapses now staggered — 10:04, 10:06,
  10:08, 10:09, 10:16, 10:18, 10:21, 10:26, 10:31, 10:38, 10:48 … instead of
  simultaneous `:00`/`:30`.
- Post-install staggered runs (all `result=success`, correct new fire times):
  chaba-cached-videos 10:06, chaba-cms-regen 10:08, kanban-sync 10:09,
  chaba-starboard-tracker 10:16, chaba-standard-drift 10:18, chaba-kanban-brief
  ~10:21, chaba-tony-ideas 10:26, served-checkout-watchdog 10:31,
  scenario-runner-drift-check 10:38, kanban-sync 10:39, chaba-starboard-tracker
  10:46, yomi-update-all 10:48, ada-jobs-verify 10:34 — all `result=success`
  at their new staggered fire times.
- Journal scan 10:07→10:39: **no board-api or CMS RemoteDisconnected/timeout
  failures** in the staggered runs. (mddb-cms embed-pool 504 "no upstream"
  WARNs continue — pre-existing embedding-capacity issue, self-requeueing,
  unrelated.)

## Known non-blocking issues found (carded)

- `lane-retention.py` crashes at summary: `sweep_ops()` returns `(line, ok)`
  tuples but the `deleted (\d+)/` regex expects strings → TypeError after the
  ops phase; all 4 weekly ada-retention-* services fail. The 09:57 catch-up
  actually ran the weekly retention early (0 deletes, some extract merges
  wrote drafts) before crashing at the summary step.
  → card `lane-retention-py-crashes-at-summary-swe-b888ce` (ADA-1370).
- board-api wedge described above → card
  `board-api-wedged-8min-on-hung-outbound-h-389be8` (KNB-1371).
- `yomi-update-active` (every 15m) fails status=125: `--network=container:yomi-api`
  but no yomi-api container/unit exists on idc03 — pre-existing, unrelated to
  jitter. (`yomi-update-all` itself ran clean at 10:48.)
  → card `yomi-update-active-update-all-fail-every-8afee2` (OPS-1382).
- `chaba-render-memory.service` fails on missing `~/.local/share/chaba/*.yml`
  inputs — hand-installed unit, pre-existing, out of scope.
- Hand-installed (non-ssot) idc03 timers still herd at `*:0/30`, `*:0/15`,
  `hourly` (chaba-nag, chaba-repeat-asks-sync, chaba-review-digest,
  mddb-embed-probe, ops-health-report, news-flood, or-credits-poll,
  wp-news-fetch, ada-memory-sync, ada-scenario-smoke, cam-wall timers).
  These are outside `ssot.jobs.yml` and were not touched; a follow-up could
  import or retire them.
- `ada-jobs-verify` 10:04 run failed on a board-api read timeout — it fired
  while board-api was still wedged (pre-restart); its 10:34 rerun succeeded
  ("no eligible cards").

## How to verify

- `ssh idc03 'systemctl --user list-timers --all | grep -E "chaba-|ada-|kanban|yomi|served|scenario"'` —
  staggered NEXT column.
- `ssh idc03 'grep OnCalendar ~/.config/systemd/user/*.timer | sort'` — no
  `*:0/30`/`*:0/15`/`hourly` among ssot-managed units.
- `ssh idc03 'sha256sum ~/CascadeProjects/chaba/scripts/board/runner-agent.py ~/.local/bin/runner-agent'` — match.
- `journalctl --user -u <unit>.service --since today` per job for run health.

lessons:
- `systemctl restart` on `Persistent=true` timers fires an immediate catch-up wave for every "missed" elapse — on a 4-core host that *is* the herd you're trying to kill. Prefer `systemctl --user reload` + let timers re-arm, or restart during a quiet window and be ready to stop catch-up services.
- ssot.jobs.yml `on_calendar` is not the whole timer fleet: idc03 has many hand-installed units still herding at `*:0/30`/`*:0/15`/`hourly` — the manifest fix only covers declared jobs.
- board-api can wedge silently: one hung outbound HTTPS call while holding both flocks froze every endpoint ~8min; only a service restart recovered it (carded KNB-1371).
- Two ssot-declared idc03 jobs (wiki-talk-watch, wp-news-morning-brief) render but were never installed — check `systemctl --user list-unit-files` before assuming `--install` covered everything.
