# Video Queue Audit Report — 2026-11-03

Read-only audit executed via `scripts/devnest/video_queue_status.py` against both video Nest roots (`gdrive:ada-nest-kk-mac-video-pilot` and `gdrive:ada-nest`).

## Executive Summary & Queue Counts

- **Audit Timestamp:** 2026-11-03T09:35:19+0700
- **Total Stale Claims:** 14 across both roots (threshold: >2.0 hours).
- **Active Claims:** 0 (all active leases are stale/orphaned).

### Queue 1: `gdrive:ada-nest-kk-mac-video-pilot`
- **Total Packages:** 54
- **Package States:**
  - `queued`: 43
  - `done`: 9
  - `failed`: 2
- **Artifact Packages:** 5
- **Stale Claims (5):**
  1. `kk-mac-storyboard-i2v-shot03-oneoff-v3-20261030` — Worker `KKs-Mac-Studio.local-43465` (Age: 76.98 hrs)
  2. `kk-mac-storyboard-i2v-shot02-20261030` — Worker `KKs-Mac-Studio.local-22648` (Age: 82.81 hrs)
  3. `kk-mac-storyboard-i2v-fullshot01-20261030` — Worker `KKs-Mac-Studio.local-14923` (Age: 85.28 hrs)
  4. `kk-mac-storyboard-i2v-probe-20261029` — Worker `192.168.2.92-59758` (Age: 97.50 hrs)
  5. `kk-mac-ltx-mps-probe-20261029` — Worker `KKs-Mac-Studio.local-34140` (Age: 107.30 hrs)

### Queue 2: `gdrive:ada-nest`
- **Total Packages:** 16
- **Package States:**
  - `done`: 14
  - `queued`: 2
- **Artifact Packages:** 5
- **Stale Claims (9):**
  1. `kk-video-c9f99fee6146-source-image-use-approved` — Worker `KKs-Mac-Studio.local-44473` (Age: 126.30 hrs)
  2. `kk-video-c9f99fee6146-embeds` — Worker `colab-bd3b5509-4645` (Age: 158.68 hrs)
  3. `ltx-probe-81f` — Worker `colab-98197cec-1620` (Age: 223.20 hrs)
  4. `ltx-probe-97f` — Worker `colab-b6bdfc08-133307` (Age: 251.51 hrs)
  5. `kk-video-c9f99fee6146-r4-preflight` — Worker `colab-07b5cf10-62428` (Age: 129.84 hrs)
  6. `kk-video-c9f99fee6146-r3-preflight` — Worker `colab-0b9f491b-17381` (Age: 135.48 hrs)
  7. `kk-video-c9f99fee6146-r2-preflight` — Worker `colab-0b9f491b-1673` (Age: 136.36 hrs)
  8. `kk-video-c9f99fee6146-preflight` — Worker `colab-8e078e8a-46874` (Age: 152.63 hrs)
  9. `ltx-probe-77f` — Worker `colab-b92f3be2-6230` (Age: 212.33 hrs)

---

## Canonical Sacred Father Packages

The project associated with the **Sacred Father** short movie (`kk-video-c9f99fee6146`, source hash `c9f99fee6146867d141a7061bdfdc71c6b15d3a617308db9420b57d67efa7cd6`) defines the following canonical packages in the shared Nest store and Chaba repo:

1. **`kk-video-c9f99fee6146-preflight` / `-r*` preflights**
   - Purpose: Validates input assets, requirements extraction, and preflight rules from `OST_-_v1_01.pdf`.
   - Status: Stale claims (e.g. `colab-8e078e8a-46874` at 152.63h, `colab-0b9f491b-1673` at 136.36h).
2. **`kk-video-c9f99fee6146-embeds`**
   - Purpose: Computes and archives T5 embeddings for all 10 story shots (`.pt` files in Drive).
   - Status: Stale claim `colab-bd3b5509-4645` at 158.68h. Note: Embeddings were successfully generated and stored, but the lock/claim lease expired without clearing.
3. **`kk-video-c9f99fee6146-source-image-use-approved`**
   - Purpose: Tracks visual audit and PDF-derived keyframe/image approvals.
   - Status: Stale claim `KKs-Mac-Studio.local-44473` at 126.30h.
4. **Associated Preview / Render Packs**
   - Staged storyboard presentation packs (`sacred-father-storyboard-summary-2026-10-30-v2.html`) and local Mac MLX alternate render pipelines.

---

## Safe Recommendations & Operational Guardrails

Per instructions (*"Do not release claims or start renders"*):

1. **Do Not Touch Active Leases Manually via Quick Hacks:** Although 14 claims are severely stale (ranging from 76 hours to over 251 hours old), clearing them requires following the standard `video-queue-claim-lifecycle-procedure.md` runbook to prevent race conditions with background Colab worker pools.
2. **Inspect Worker Epochs:** The stale claims belong to expired worker sessions (`KKs-Mac-Studio.local-*` and `colab-*`). Since these runs finished or aborted days ago, schedule an authorized queue maintenance sweep to garbage-collect expired `claim/` directories for completed or superseded packages.
3. **Preserve Sacred Father Artifacts:** T5 embedding tensors (`.pt`) and visual assets in `gdrive:ada-nest/projects/kk-video-c9f99fee6146/` are verified intact. Do not delete completed output directories or successful preflight artifacts.
4. **Resume Strategy:** For uncompleted/queued storyboard shots, spin up fresh worker instances with updated environment dependencies (resolving prior TorchAO / Diffusers import issues) rather than retrying against stale lease tokens.
