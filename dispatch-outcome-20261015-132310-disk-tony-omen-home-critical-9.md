# Dispatch outcome — disk-auto-tony-omen-home (attempt 2)

## Result

tony-omen `/home` **99% → 59%** (3.7G → 122G free, ~118G reclaimed). Alert condition cleared; verified live over SSH after each step.

## Root cause

The card's earlier fix (2026-10-11 move-cache) held — HF cache stayed on /data — but new growers appeared:

- **`~/.config/gev-cast-profile/BrowserMetrics` = 42G**: 10,678 leaked Chromium `BrowserMetrics-*.pma` files (4MiB each, ~2/min while a headless/cast Chrome runs). Invisible to disk-trend-watch because the du watchlist only covered `~/.cache` + `/var/log`.
- **`~/mddb-backups-idc01-retired` = 64G**: retired idc01 mddb dumps left on /home by the 10-11 pass.
- **`~/.local/share/devin/cli` backups ≈ 19G**: three ~5.8G sessions.db snapshots + a manual .bak (sessions.db itself is 5.8G).
- Active data left alone: model-bench 18G, .ollama 18G (10-13/14 model pulls — the ~51G single-day jump was these + .pma).

## Actions taken

On tony-omen (via SSH):
1. Deleted 10,669 `.pma` files (kept newest 10) — ~42G freed.
2. `mv mddb-backups-idc01-retired → /data/backups/` + symlink at original path — 64G off /home.
3. `mv` 2 old devin-cli backups + `sessions.db.bak-20261013` → `/data/backups/devin-cli/` — ~13.5G (newest backup kept on /home).
4. Installed interim cron: `*/30 * * * * find /home/tony/.config -maxdepth 2 -name 'BrowserMetrics-*.pma' -mmin +120 -delete`.

In this worktree (durable repo fixes, uncommitted→committed on dispatch branch):
- `scripts/system-maintenance.mjs`: added `browserMetricsCleanup()` — keeps 50 newest `.pma` per `~/.config/*/BrowserMetrics`; runs via omen's existing daily 03:00 cron.
- `scripts/ada/disk-trend-watch.py`: added `$HOME/.config/*/BrowserMetrics` to default `DISK_TREND_DU_ROOTS` so the leak class is trended.
- Job record: `docs/ssot/jobs/infrastructure/2026-10-15-tony-omen-home-disk-cleanup.yml`.

## Verify

- `ssh tony-omen 'df -h /home'` → 59%.
- `ssh tony-omen 'ls /home/tony/mddb-backups-idc01-retired | head'` → resolves via symlink to /data.
- `ssh tony-omen 'crontab -l | tail -1'` → .pma prune line.

## Watch / follow-ups

- `/data` now 86% (42G free) after absorbing ~77G; mddb-backup-pull has no retention (~3.4G/day). `disk-auto-tony-omen-data` may re-open — needs keep-N or gdrive tier decision.
- Remove omen's interim cron line once the system-maintenance.mjs change merges + pulls.
- gev-cast Chrome launcher not located (not in omen crontab/user-systemd/repo greps) — source fix would be `--disable-metrics` or equivalent.

lessons:
- Chromium `BrowserMetrics-*.pma` leak: ~4MiB/file, ~2/min in headless/cast profiles; check `.config/*/BrowserMetrics` on any host running cast Chromes.
- disk-trend DU_ROOTS only watched `.cache`/`/var/log` — growth in `.config`/dotdirs was invisible; watchlist now covers BrowserMetrics.
- Remote `mv` across filesystems outlives the SSH session (survived disconnect and finished) — still, prefer running big moves under `nohup`/separate calls so one timeout can't orphan mid-list steps.
- Cron lines via ssh heredoc mangle `&&` — use `find ... -delete` primitives instead of shell conjunctions.
- devin-cli `sessions.db` bloat (5.8G on omen) makes every auto-backup multi-GB; vacuum would shrink all copies.
