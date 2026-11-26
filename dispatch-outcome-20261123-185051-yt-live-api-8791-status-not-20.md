# Dispatch outcome — vcast-auto-yt-live-api (:8791/status not 200)

## What was wrong

`GET http://tony-omen.taila0626a.ts.net:8791/status` → connection refused.
On tony-omen the `yt-live-api.service` **user** unit was `inactive (dead)` **and
`disabled`** — it was never re-enabled after the phase-5 LAN migration
(2026-10-19/20), so omen's 18:51 reboot left it down permanently (sibling
`raceman-web` was enabled; `yt-live-api` was not). The card had already
flagged it at 16:19, before that reboot — the unit was dead even earlier.

Deeper drift found while verifying (verify-by-surface, not just the health
endpoint):

- `~/.local/bin/yt-live.sh` on omen was the **pre-dub Oct-5 snapshot** carried
  from dell — hardcoded `APP_DIR=~/CascadeProjects/chaba-tony-dell/.../apps/yt-live`
  (does not exist on omen) and `BASE_URL=http://192.168.2.67/apps/yt-live`
  (port 80 — nothing listens). Last media write in the served dir: **Oct 18** —
  no successful cast on omen since migration.
- `~/.local/bin/yt-live-api.py` was a divergent hotfixed variant: it had
  `fast_cast` (direct .mp4 → HA play_media) + `GET /list` that Ada's
  `yt(action=list|cast)` depends on, but **lacked** the repo's
  `YT_LIVE_APP`/`YT_LIVE_MCACHE` env overrides, `voice` param and dub state.
- Repo `scripts/ops/yt-live-api.py` conversely lacked `fast_cast`/`/list` —
  bidirectional drift.

## What changed

**Live on tony-omen (verified):**

- `systemctl --user enable --now yt-live-api` → active + enabled (survives reboot).
- New drop-in `~/.config/systemd/user/yt-live-api.service.d/override.conf`:
  `YT_LIVE_APP=/home/tony/CascadeProjects/chaba-raceman/public/apps/yt-live`,
  `YT_LIVE_BASE=http://192.168.2.67:8083/apps/yt-live` (omen owns 192.168.2.67
  on wlo1; raceman-web nginx :8083 serves `/apps/yt-live` from the
  chaba-raceman checkout).
- Installed the repo pipeline file set to `~/.local/bin` (the
  `yt-pipeline-install.sh` manifest): yt-live.sh, yt-live-api.py,
  yt-vtt-dub.py, yt-vtt-translate.py, yt-cast-detect.py, yt-whisper-vtt.py,
  yt-diarize.py, yt-diarize-remote.sh, yt-dub-fixmap.th.json.

**In this worktree (commit `0bd6ccc912` on dispatch branch):**

- `scripts/ops/yt-live-api.py` — merged: repo env/voice/dub features **plus**
  restored `fast_cast` + `/list`; `/list` now derives its dir from
  `YT_LIVE_APP` and URLs from `YT_LIVE_BASE` (no more hardcoded raceman path).
- `docs/ssot/apps/ssot.apps.vcast.yml` — yt-live-api entry updated
  (tony-dell → tony-omen, raceman media, env contract).
- `docs/ssot/infrastructure/ssot.migrated-units.yml` — recorded the
  `override.conf` drop-in + `nodered-ha.env` secret dependency.
- `docs/ssot/jobs/vcast/2026-11-23-yt-live-api-omen-restore.yml` — full trail.

## Verification

- `curl http://tony-omen.taila0626a.ts.net:8791/status` → **200**,
  `{segments: 1528, vod_complete: true, subtitles: true, phase: complete}`
  (real data — proves `YT_LIVE_APP` reached the api).
- `/list` → 10 cast-ready files with `http://192.168.2.67:8083/apps/yt-live/…`
  URLs; one URL fetched → 200 (~170 MB mp4).
- `/health` → `{"ok": true}`; `yt-live.sh` passes `bash -n`.
- `systemctl --user is-enabled yt-live-api` → `enabled`, `is-active` → `active`.

## Residual / notes

- Omen's reboot also left `plug-watch`, `ha-live` (`:8444` tailscale-serve →
  502), `ha-stall-watchdog`, `playlive-chrome`, `yolo-detect` inactive+disabled.
  Not covered by this card and possibly intentional — flagged in card comms
  for the audit/health lanes.
- Repo script defaults still point at dell paths; the unit env override is the
  omen contract (now documented in SSOT). If yt-live ever moves again, the
  drop-in must move with it.
- Card comms posted to `vcast-auto-yt-live-api`.

## Lessons

- Migrated user units can be left `disabled` — check `is-enabled`, not just
  `is-active`; a disabled unit silently never starts at boot.
- Installed `~/.local/bin` pipeline drifted **both** ways vs repo (omen had
  pre-dub yt-live.sh + hotfixed yt-live-api.py). Reconcile before assuming env
  overrides reach the code.
- `/status` 200 was true while the cast path was still broken — verify the
  consumer path, not just the health endpoint.
- `ssh tony-omen` timed out once; the tailscale IP `100.75.102.88` worked.
