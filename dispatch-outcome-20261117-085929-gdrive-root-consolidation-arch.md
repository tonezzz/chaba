# Dispatch outcome — gdrive-root-consolidation-arch (2026-11-17, idc02)

Card: `gdrive-root-consolidation-archive-dead-p-9c04d1` (OPS-1187)

## What this session found

Phase B was executed 2026-11-08 by a stampede of ~8 concurrent dispatch
sessions (Tony had answered "proceed" on every gate request). Verified
server-side today: the folds landed, but three consumer-side breaks were
left behind, and the audit/plan/registry docs sat unmerged in dead
dispatch branches (132453, 132553, 132902 — the latter still exist
locally; a proper closeout never shipped).

Verified root state (`rclone lsd gdrive:`): chaba-owned roots are now
`ada-nest`, `ada-nest-adobe-stock` (pending drain), `archive`, `backups`,
`colab-cache`, `nest`, `notebooklm`. Folded on 11-08:
`ada-nest/{devnest,kk-llm,kk-mac-video-pilot,adobe-stock,documents}`,
`archive/{appsheet,chaba,colabgpu,cold-storage,chaba-media-corpus}`,
`backups/devin`.

## What this session did

**Drive side:**
- `rclone rmdir gdrive:tmp-sc-test` — empty scratch dir from the stampede.
- `rclone moveto gdrive:ada-nest/documents → ada-nest/ada-documents` —
  **break fix**: `doc_archive.py`/`gdrive-archive.py` resolve the root by
  folder *name* (`find(name)` is a global name query, `DRIVE_ROOT` is a
  name not a path); the fold's `documents` rename would have made the next
  archive run `mkdir` a fresh empty `ada-documents` root and split-brain
  the 557-doc archive.
- `rclone copy ada-nest-adobe-stock → ada-nest/adobe-stock` — caught up 4
  stragglers written post-fold (SESSION.json, 40-qc-review.md,
  comparison-e-cf-inpaint-wheels.{png,manifest.json}) + refreshed indexes.
  New dir now equals old root exactly: 41 obj / 81.867 MiB.

**Repo side (commit `de26ea9ffa` on the dispatch branch):**
- `scripts/adobe-stock/*` (7 files) — `ADA_ADOBE_STOCK_REMOTE` default now
  `gdrive:ada-nest/adobe-stock`.
- `video_queue_status.py` — `KK_MAC_VIDEO_PILOT_REMOTE` default →
  `gdrive:ada-nest/kk-mac-video-pilot` (old root gone — default was dead).
- `deploy-card.sh` — `CHABA_GDRIVE_BUNDLES` default →
  `gdrive:archive/chaba/bundles` (chaba root gone; a deploy would have
  resurrected it; `bundles/` never existed — write-only cold tier).
- `ada-ha.container` — yt-corpus `Volume=` →
  `~/GoogleDrive/archive/chaba-media-corpus/yt-live-media`.
- `gdrive-archive.py` — `DRIVE_ROOT` env override (default `ada-documents`).
- Env knobs, defaults unchanged: `NEST_BRAINS_REMOTE` (nest-brain-*.sh),
  `NOTEBOOKLM_KB_COLLECTION` (notebooklm-kb-sync.py).
- Doc/test ref fixes: doc_archive.py, README, env.example, kb doc,
  ssot.apps.ada-memory-banks.yml, test_nest_worker_scan.py, colab pack.
- Restored + updated the unmerged trail docs:
  `ssot.gdrive-roots.yml` (now final-state registry),
  `docs/kb/gdrive-root-consolidation.md`, plus the three 11-08
  audit/plan yml files, and wrote
  `docs/ssot/jobs/infrastructure/2026-11-17-gdrive-root-consolidation-closeout.yml`.

## Verification done

- `python3 -m unittest tests.devnest.test_gdrive_roots` — 4/4 pass.
- `py_compile` on all edited .py, `bash -n` on edited .sh — clean.
- YAML parse on all new/edited yml — clean.
- `rclone size` old-vs-new adobe-stock — identical (41 obj / 81.867 MiB).
- `rg 'gdrive:<old-root>'` over scripts/stacks/systemd/tests/apps — zero stale refs.

## Remaining (host-gated, documented in closeout yml)

1. **Drain `gdrive:ada-nest-adobe-stock`** — dell `reindex-sync.timer`
   wrote indexes at 08:37 today (pre-merge code). After this branch merges
   and `chaba-repo-sync.timer` pulls it (~15–60 min), drain:
   `rclone move gdrive:ada-nest-adobe-stock gdrive:ada-nest/adobe-stock`
   then rmdir.
2. **`nest/brains → ada-nest/brains`** (approved req 167376) — needs the
   dell gcrypt remote repoint + `NEST_BRAINS_REMOTE` set on dell BEFORE
   the move; otherwise the crypt layer recreates the old root.
3. **ada-ha restart on tony-dell** — picks up the repointed corpus Volume.

## Note

board-api `/comment` POST hung repeatedly from idc02 (GET /health answers
400 instantly; POSTs time out — write flock looks wedged). The status comm
is queued in `/tmp/board-comm.json`; card state is fully reflected in the
closeout yml which lands via the dispatch merge.
