# Dispatch outcome — gdrive-root-consolidation-arch (2026-11-08 13:30, tony-macbook)

Card: `gdrive-root-consolidation-archive-dead-p-9c04d1` (OPS-1187)

## What this session found

This card is being worked by **multiple concurrent dispatch sessions** today
(132902 and 133001 on idc02, 132744 + this one on tony-macbook). Verified
server-side state at ~13:34:

**Confirmed done by siblings:**
- `gdrive:appsheet` -> `gdrive:archive/appsheet` — 23 files, 1.1MB (verified present)
- `gdrive:DevinBackups` -> `gdrive:backups/devin` — 3 files, 31.8GB session-DB backups (verified)
- `tmp/`, `tmp-test/` removed earlier; `appsheet` gone from root

**In progress right now (another session):**
- Copy-first fold of `gdrive:ada-nest-kk-llm` -> `gdrive:ada-nest/kk-llm`:
  grew 208 -> 254 -> 275 files during this session's audit window (~4 min).
- `gdrive:ada-nest/{devnest,adobe-stock,kk-mac-video-pilot}` not yet created.
- `tmp-sc-test/` (empty, created 13:31) — likely sibling scratch dir; left alone.

**Consumer audit result (independent, agrees with sibling):**
every remaining phase-B root dir has >=1 live consumer —
- `ada-nest-adobe-stock` — 7 scripts in `scripts/adobe-stock/` (defaults baked in;
  `reindex-sync.service` timer on tony-dell; dir written 2026-11-06)
- `ada-nest-devnest` — `devnest_capacity_broker.py`, `devnest_report_feed.py`,
  `kk_mac_plan_validator.py` (tony-dell timers)
- `ada-nest-kk-llm` — `kk_mac_capacity_producer.py`, `kk_mac_metrics.py`,
  `devnest_capacity_broker.py`
- `ada-nest-kk-mac-video-pilot` — `video_queue_status.py` default remote list
  (9.6GB of renders)
- `backups` — DR path: `mddb-gdrive-tier.service`, `mddb-standby-pull.service`,
  cold-restore runbooks; `backups/devin` written today 13:28 — DO NOT MOVE
- `nest/brains` — `nest-brain-pack.sh` / `nest-brain-restore.sh`
- `chaba` — `deploy-card.sh` pushes `gdrive:chaba/bundles/`; `chaba/colabgpu` stale since 2025-11
- `ada-documents` — doc-archive stack (`stacks/idc01/doc-archive`)
- `chaba-media-corpus` — mounted into ada-ha container via Google-Drive-desktop
  path `~/GoogleDrive/chaba-media-corpus/yt-live-media` — moving breaks the mount
- `colab-cache` — documented procedure path `MyDrive/colab-cache/` (colab notebooks, external)

## What this session did

- Posted a verification comm on the card: confirmed sibling moves, flagged the
  in-progress fold, noted the drain-window risk (files written to root
  `ada-nest-kk-llm` after the copy pass but before the B2 drain will be
  orphaned — drain must re-run at cutover).
- **Made zero drive changes** — a concurrent session is mid-copy on the same
  dirs; acting would collide (double copies, divergent partial state).
- Made zero repo changes — siblings already staged the plan doc
  (`docs/ssot/jobs/infrastructure/2026-11-08-gdrive-root-consolidation-phase-b.yml`),
  `scripts/ops/gdrive-root-consolidate.sh`, and env-override prep in their
  worktrees; duplicating would collide on merge.

## Open decisions (both raised by siblings, still `status: open`)

- `phase-b-every-remaining-root-dir-is-a-li-7a4820` — close-as-hold vs attended
  nest-in vs partial.
- `phase-b-layout-for-the-4-ada-nest-lane-d-b4fc84` — (a) nest the 4 lane dirs
  under `gdrive:ada-nest/` vs (b) leave flat; also needs OK from the
  kk-mac-video-render-lane session before moving that dir.

## How to verify

- `rclone lsd gdrive:` — root dir count vs the ~73 baseline
- `rclone size gdrive:ada-nest/kk-llm` — fold progress (275 files at 13:34;
  root `ada-nest-kk-llm` = 453 files, drain still needed)
- Card comms on `gdrive-root-consolidation-archive-dead-p-9c04d1` for the
  running log across all sessions.
