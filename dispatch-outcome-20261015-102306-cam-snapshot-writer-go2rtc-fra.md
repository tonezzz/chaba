# Dispatch outcome — cam-snapshot-writer-wp

Branch: `dispatch/20261015-102306-cam-snapshot-writer-go2rtc-fra` (worktree
commit `80812128` — not pushed, not deployed per dispatch rules).

## What was built

**`scripts/cam-wall/cam-snapshot-wp.py`** — the cam recorder. Runs on
tony-dell (go2rtc aggregator host; the API is loopback-only) on
`wp-cam-snapshot.timer`. Each run:

1. Enumerates cameras from the `streams:` section of
   `~/.config/go2rtc/go2rtc.yaml` (indent-based parse, no yaml dep;
   falls back to `GET /api/streams` if the file yields nothing).
   `CAM_SNAPSHOT_SKIP` excludes names.
2. **Collapses quality variants** — `*_hd`/`_low`/`_sd` map onto their
   base stream when the base is configured (same physical camera;
   `cam-wall-pull.py` convention). `CAM_SNAPSHOT_ALL_STREAMS=1` disables.
   Frame fetch tries `[cam, cam_hd, cam_low, cam_sd]` and takes the
   first live frame (auto/adaptive streams can 200-with-empty-body while
   the dedicated variant is alive).
3. Uploads the frame: `POST /wp/v2/media` (jpeg, filename
   `cam-<id>-<ts>.jpg`).
4. Creates the private snapshot post: title `Cam — <id> <ts>` (SSOT
   title standard), deterministic slug `cam-<id>-<yyyymmdd-HHMMSS>`,
   meta `camera_id`/`captured_at`/`kind=live`/`stream_url`
   (`<go2rtc>/stream.html?src=<cam>`), `featured_media`=the attachment,
   `date`=capture time so retention's `before` filter is exact.
   Post-create failure deletes the just-uploaded attachment — no orphans.
5. **Upserts the per-camera directory post** — slug `cam-<id>`,
   `kind=live`; its featured image and `captured_at` refresh to the
   newest frame every run (the card's "seed kind=live directory posts").
6. **Retention**: lists cam posts with post date < now-7d
   (`?before=`), force-deletes every post matching the snapshot slug
   pattern, then force-deletes its featured attachment. Directory posts
   (no timestamp in slug) are never purged.

Flags: `--dry-run` (discovery + fetch, zero WP writes), `--cams=a,b`,
`--seed-only`, `--purge-only`. A dead camera fails loudly per-cam but
doesn't fail the run; all-cams-fail or no roster exits 2.

**`ssot.jobs.yml`** — new job `wp-cam-snapshot` (host tony_dell, systemd,
`OnCalendar=*-*-* *:2/15:00`, Persistent, 5m timeout; the :02 offset
spreads it off cam-wall-cms's `*:0/15` tick). Rendered to
`systemd/generated/tony_dell/wp-cam-snapshot.{service,timer}` via
`render-jobs.py` (the render also emitted the pending
`qc-scoreboard` units — manifest was ahead of the tree).

**`ssot.wp-boards.yml`** — cam row now documents the two row shapes
(snapshot vs directory, both kind=live, discriminate by slug); `writers:`
gains the `cam_snapshot` entry.

**`docs/ssot/jobs/infrastructure/2026-10-15-cam-snapshot-writer-wp.yml`** —
trail doc with data model, install runbook, manual-run flags.

## Result

- `python3 -m unittest tests.camwall.test_cam_snapshot_wp` — **6/6 pass**
  (FakeNet transport: fake go2rtc frames + fake WP REST store; covers
  yaml parse, `/api/streams` fallback, variant collapse + fallback,
  full run, 7d purge incl. attachment delete, dry-run purity, seed-only).
- `python3 scripts/render-jobs.py --check` — manifest OK (56 jobs).
- `node scripts/ssot-validate-all.mjs` — my files all valid; the 1 error
  is pre-existing (`jobs/kanban/2026-10-15-board2-living-board.yml`,
  unrelated) and the ssot.jobs.yml 755>750-line flag is a bloat warning.
- Live WP verified reachable + `cam` CPT registered
  (`GET /wp/v2/types` on the origin). Auth'd write path not exercised —
  `wp-boards.env` isn't on idc02 and the writer is host-bound anyway.

## Spec notes

- Card note is truncated at 500 chars by board-api — ends mid-sentence
  ("Also seed kind=live directory posts for sso"). Implemented the
  directory-post half literally; raised board request
  `card-note-truncates-mid-sentence-also-se-f5f523` with options —
  unanswered at close (non-blocking; a consuming surface can key off
  slug `cam-<id>` posts without writer changes).
- `kind=live` applied verbatim to both row kinds per the card text.

## How to verify / install

Post-merge, on tony-dell:

```bash
cd ~/CascadeProjects/chaba-tony-dell && ./scripts/git-safe-pull.sh
python3 scripts/render-jobs.py --host tony_dell --install
python3 scripts/cam-wall/cam-snapshot-wp.py --dry-run   # roster + frames
systemctl --user start wp-cam-snapshot.service
journalctl --user -u wp-cam-snapshot -n 30
# expect per cam: "snap=<id> dir=<id>(created|updated) frame=<n>B src=<s>"
```

Then wp-admin → Cams shows private snapshot rows + one directory row per
camera (Camera/Captured/Kind columns already registered in the plugin).

## Summary

Built the cam snapshot writer per the card: `scripts/cam-wall/cam-snapshot-wp.py`
enumerates go2rtc streams from `~/.config/go2rtc/go2rtc.yaml` (collapsing
`_hd`/`_low`/`_sd` variants onto their base camera), pulls
`api/frame.jpeg` per cam with variant fallback, uploads each frame as a
WP attachment, writes a private `cam` post (`Cam — <id> <ts>`, kind=live,
camera_id/captured_at/stream_url meta, featured image = frame), upserts a
stable per-camera directory post (slug `cam-<id>`), and purges snapshot
posts plus their attachments older than 7 days each run. It's registered
as job `wp-cam-snapshot` in ssot.jobs.yml (tony_dell, every 15 min at :02)
with rendered units in systemd/generated/tony_dell/. Tests 6/6 pass
against a fully fake go2rtc+WP transport; install on tony-dell is the
one-line post-merge step in the jobs doc.
