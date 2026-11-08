# Video Stale Claim Reconciliation Report

- **Audit Timestamp:** 2026-11-03T09:35:19+0700 (Reconciled per card spec)
- **Target Roots:** `gdrive:ada-nest-kk-mac-video-pilot`, `gdrive:ada-nest`
- **Total Stale Claims Audited:** 14 (all active leases are stale / orphaned > 2 hours)

---

## 1. Inventory & Stale Claim Breakdown

### Queue 1: `gdrive:ada-nest-kk-mac-video-pilot` (54 Packages)
- **States:** 43 queued, 9 done, 2 failed
- **Stale Claims (5):**
  1. `kk-mac-storyboard-i2v-shot03-oneoff-v3-20261030` — Worker `KKs-Mac-Studio.local-43465` (76.98 hrs)
  2. `kk-mac-storyboard-i2v-shot02-20261030` — Worker `KKs-Mac-Studio.local-22648` (82.81 hrs)
  3. `kk-mac-storyboard-i2v-fullshot01-20261030` — Worker `KKs-Mac-Studio.local-14923` (85.28 hrs)
  4. `kk-mac-storyboard-i2v-probe-20261029` — Worker `192.168.2.92-59758` (97.50 hrs)
  5. `kk-mac-ltx-mps-probe-20261029` — Worker `KKs-Mac-Studio.local-34140` (107.30 hrs)

### Queue 2: `gdrive:ada-nest` (16 Packages)
- **States:** 14 done, 2 queued
- **Stale Claims (9):**
  1. `kk-video-c9f99fee6146-source-image-use-approved` — Worker `KKs-Mac-Studio.local-44473` (126.30 hrs)
  2. `kk-video-c9f99fee6146-embeds` — Worker `colab-bd3b5509-4645` (158.68 hrs)
  3. `ltx-probe-81f` — Worker `colab-98197cec-1620` (223.20 hrs)
  4. `ltx-probe-97f` — Worker `colab-b6bdfc08-133307` (251.51 hrs)
  5. `kk-video-c9f99fee6146-r4-preflight` — Worker `colab-07b5cf10-62428` (129.84 hrs)
  6. `kk-video-c9f99fee6146-r3-preflight` — Worker `colab-0b9f491b-17381` (135.48 hrs)
  7. `kk-video-c9f99fee6146-r2-preflight` — Worker `colab-0b9f491b-1673` (136.36 hrs)
  8. `kk-video-c9f99fee6146-preflight` — Worker `colab-8e078e8a-46874` (152.63 hrs)
  9. `ltx-probe-77f` — Worker `colab-b92f3be2-6230` (212.33 hrs)

---

## 2. Classification of Stale Claims

Per the `video-queue-claim-lifecycle-procedure.md` and `video-history-data-management-procedure.md` runbooks, every stale claim is classified into one of four categories:

### A. Historical / Support Packages & Probes
- **Packages:** `kk-mac-storyboard-i2v-probe-20261029`, `kk-mac-ltx-mps-probe-20261029`, `ltx-probe-81f`, `ltx-probe-97f`, `ltx-probe-77f`.
- **Classification:** Historical / Support (Probe/Diagnostics).
- **Recommendation:** **Retire.** These exploratory LTX model probes and local test scripts successfully served their purpose and are superseded by newer pipeline iterations. Mark as retired (preserve claim history and logs in cold archive; do not rerun).

### B. Done Artifact Packages
- **Packages:** `kk-video-c9f99fee6146-embeds`, `kk-video-c9f99fee6146-source-image-use-approved`.
- **Classification:** Done-artifact (Completed work with persistent outputs in Drive, but abandoned claim markers).
- **Recommendation:** **Hold / Retain.** T5 tensor embedding files (`.pt`) and visual audit sign-offs are verified intact in Drive. Close history and preserve artifacts; do not rerun automatically.

### C. Failed / Superseded Preflight Runs
- **Packages:** `kk-video-c9f99fee6146-preflight`, `kk-video-c9f99fee6146-r2-preflight`, `kk-video-c9f99fee6146-r3-preflight`, `kk-video-c9f99fee6146-r4-preflight`.
- **Classification:** Failed / Superseded preflight iterations.
- **Recommendation:** **Retire.** These Colab-executed preflight runs were superseded by subsequent manifest iterations (`-r4` and finalized story packages). Keep failure logs for audit and release claim markers.

### D. Canonical Current Sacred Father Candidate Packages
- **Packages:** `kk-mac-storyboard-i2v-shot03-oneoff-v3-20261030`, `kk-mac-storyboard-i2v-shot02-20261030`, `kk-mac-storyboard-i2v-fullshot01-20261030`.
- **Classification:** Canonical current **Sacred Father** candidate packs (Storyboard I2V shots linked to `kk-video-c9f99fee6146`).
- **Recommendation:** **Release & Requeue.** These active storyboard shot packs represent valid ongoing rendering work for the Sacred Father short movie (`kk-video-c9f99fee6146`). Release their stale claim markers per standard cleanup procedure (retaining manifest and assets) so that an authorized single worker can claim and complete them.

---

## 3. Operational Directives & Guardrails

1. **Read-Only Compliance:** No queue mutations or claim deletions were performed during this audit session.
2. **Claim History Preservation:** Original worker IDs, timestamps, and claim directories remain fully intact in storage history.
3. **Queue Maintenance Protocol:** When authorized, execution follows `video-queue-claim-lifecycle-procedure.md` §6 (removing only claim markers for canonical packages, and marking probes/preflights as retired).
