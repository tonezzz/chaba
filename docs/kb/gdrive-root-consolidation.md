# Gdrive root consolidation — OPS-1187

Registry: `docs/ssot/infrastructure/ssot.gdrive-roots.yml` (per-dir consumers, sizes, verdicts).

## Status

- **Phase A — done 2026-11-08.** 6 docs-only-referenced pilot dirs moved to
  `gdrive:ada-nest/archive/` (cline-pilot, cline-pilot-rerun-20261028-ada,
  cline-test-run-20261029-r1, kk-mac-docpilot-static-qc-ops0904, kk-mac-pilot,
  kk-mac-render-smoke ~9GB). Removed truly-empty `tmp/`, `tmp-test/`.
- **Phase B — executed 2026-11-08, closed out 2026-11-17.** After the audit
  below recommended hold, Tony answered "proceed" on all gate requests and a
  batch of concurrent dispatch sessions folded the live roots:
  `ada-nest-{adobe-stock,devnest,kk-llm,kk-mac-video-pilot}` → `ada-nest/<lane>`;
  `ada-documents` → `ada-nest/ada-documents`; `appsheet`, `chaba`, `colabgpu`,
  `cold-storage`, `chaba-media-corpus` → `archive/`; `DevinBackups` →
  `backups/devin`. Repo repoints + remaining host-gated steps:
  `docs/ssot/jobs/infrastructure/2026-11-17-gdrive-root-consolidation-closeout.yml`.
  Kept at root: `ada-nest`, `backups`, `archive`, `nest`, `colab-cache`,
  `notebooklm` (+ one pending drain: `ada-nest-adobe-stock`).

## Why root renames are not tidying

Three independent consumer surfaces pin each root dir's name:

1. **rclone remote strings** — `gdrive:<dir>` hardcoded in `scripts/`,
   `systemd/`, `stacks/` (no central remote config; ~15 hardcoded defaults).
2. **Whole-Drive FUSE mount** — `~/GoogleDrive` on tony-dell exposes the root
   namespace as paths. `stacks/tony-dell/ada-ha/ada-ha.container` mounts
   `~/GoogleDrive/chaba-media-corpus/yt-live-media`; the backup stack uses
   `~/GoogleDrive/Tony AI/backup/chaba`. A Drive-side rename silently breaks
   the mount path.
3. **External consumers** — Colab notebooks (`MyDrive/colab-cache/`,
   `MyDrive/ada-nest/queue`), kk-mac workers polling `ada-nest/kk-llm/inbox/`,
   Mac Studio render workers claiming in `ada-nest/kk-mac-video-pilot`, ada-voice
   backend (separate repo) writing `ada-documents`.

## Phase-B verdict (audited 2026-11-08; superseded by execution)

The audit recommended hold — every root was a live API contract. Tony
overrode with "proceed" on all gate requests, so the folds went ahead.
Post-execution lessons worth keeping:

- `ada-documents` was folded to `ada-nest/documents`, but doc-archive's
  `DRIVE_ROOT` lookup is **by folder name, not path** — the rename would
  have split-brained the next archive run. Fixed 2026-11-17 by renaming the
  folded dir back to `ada-documents` (now `ada-nest/ada-documents`).
- `ada-nest-adobe-stock`'s copy-first fold went stale: the dell
  reindex-sync.timer kept writing indexes/campaign files to the old root.
  Repoint-first ordering matters — drain the old root only after the
  consumer's exec checkout syncs the new default.
- `backups/` is still the DR cold tier — never rename. `colab-cache`,
  `notebooklm`, `nest/brains` and `Tony AI/` remain root contracts.

If a root ever must move anyway:

1. Edit every `gdrive:<old>` literal in repo (scripts, systemd, stacks) to the
   new path; prefer env-overridable defaults (`${VAR:-gdrive:<new>}`).
2. Merge to master; wait ≥1 `chaba-repo-sync.timer` cycle (~15–60 min per
   host) so exec checkouts run new code.
3. `rclone moveto gdrive:<old> gdrive:<new>` — server-side rename, instant,
   no transfer quota. Verify: `rclone lsd gdrive:<new>` + `rclone lsd gdrive:`
   shows old gone.
4. Fix non-repo consumers: colab notebook cells, FUSE-mount `Volume=` lines in
   quadlets, external-repo defaults (ada-voice).
5. Consumer proof, not just producer: run one real consumer (e.g.
   `video_queue_status.py`, `campaign-status.py`) against the new path.
