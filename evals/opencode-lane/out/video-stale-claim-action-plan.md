# Video Dispatcher Claim and Queue Reconciliation Plan

## Executive Summary

This plan provides the structured reconciliation strategy for the 14 stale claims identified across the two active Google Drive video queues (`gdrive:ada-nest-kk-mac-video-pilot` and `gdrive:ada-nest`), based on the current video queue status report (`reports/video-queue-status-2026-11-03.json`) and the video queue claim-lifecycle procedure (`docs/kb/video-queue-claim-lifecycle-procedure.md`).

---

## 1. Queue Status Inventory

As of `2026-11-03T09:35:19+0700`:

* **`gdrive:ada-nest-kk-mac-video-pilot`**
  * Total packages: 54
  * States: `queued` = 43, `done` = 9, `failed` = 2, `active_claims` = 0, `stale_claims` = 5
  * Artifact packages: 5

* **`gdrive:ada-nest`**
  * Total packages: 16
  * States: `done` = 14, `queued` = 2, `active_claims` = 0, `stale_claims` = 9
  * Artifact packages: 5

* **Summary Metrics**:
  * Total active claims: 0
  * Total stale claims: 14 (ranging in age from ~77 hours to ~251.5 hours)

---

## 2. Stale Claim Breakdown & Categorization

Per the queue lifecycle procedure, every stale claim must be inspected and classified into one of four deterministic actions: **Close/Retire**, **Release & Requeue**, **Preserve as Artifact**, or **Hold for Review**.

### A. Pilot Queue (`gdrive:ada-nest-kk-mac-video-pilot`) — 5 Stale Claims

1. **`kk-mac-storyboard-i2v-shot03-oneoff-v3-20261030`**
   * Worker: `KKs-Mac-Studio.local-43465` | Age: 76.98 hours
   * Classification: *Support / variant / experimental render*
   * Action: **Retire** (mark as retired with reason; preserve artifacts/history, do not rerun).

2. **`kk-mac-storyboard-i2v-shot02-20261030`**
   * Worker: `KKs-Mac-Studio.local-22648` | Age: 82.81 hours
   * Classification: *Support / variant / experimental render*
   * Action: **Retire** (mark as retired with reason; preserve artifacts/history).

3. **`kk-mac-storyboard-i2v-fullshot01-20261030`**
   * Worker: `KKs-Mac-Studio.local-14923` | Age: 85.28 hours
   * Classification: *Support / variant / experimental render*
   * Action: **Retire** (mark as retired with reason; preserve artifacts/history).

4. **`kk-mac-storyboard-i2v-probe-20261029`**
   * Worker: `192.168.2.92-59758` | Age: 97.50 hours
   * Classification: *Probe / diagnostic package*
   * Action: **Retire** (mark as retired; old probe/support package).

5. **`kk-mac-ltx-mps-probe-20261029`**
   * Worker: `KKs-Mac-Studio.local-34140` | Age: 107.30 hours
   * Classification: *Probe / diagnostic package*
   * Action: **Retire** (mark as retired; old probe/support package).

---

### B. Core Queue (`gdrive:ada-nest`) — 9 Stale Claims

1. **`kk-video-c9f99fee6146-source-image-use-approved`**
   * Worker: `KKs-Mac-Studio.local-44473` | Age: 126.30 hours
   * Classification: *Preflight / support metadata package*
   * Action: **Retire** (mark as retired; preserve lineage).

2. **`kk-video-c9f99fee6146-embeds`**
   * Worker: `colab-bd3b5509-4645` | Age: 158.68 hours
   * Classification: *Support / embedding helper package*
   * Action: **Retire** (mark as retired).

3. **`ltx-probe-81f`**
   * Worker: `colab-98197cec-1620` | Age: 223.20 hours
   * Classification: *Probe package*
   * Action: **Retire** (old probe package).

4. **`ltx-probe-97f`**
   * Worker: `colab-b6bdfc08-133307` | Age: 251.51 hours
   * Classification: *Probe package*
   * Action: **Retire** (old probe package).

5. **`kk-video-c9f99fee6146-r4-preflight`**
   * Worker: `colab-07b5cf10-62428` | Age: 129.84 hours
   * Classification: *Preflight support package*
   * Action: **Retire** (preflight support package).

6. **`kk-video-c9f99fee6146-r3-preflight`**
   * Worker: `colab-0b9f491b-17381` | Age: 135.48 hours
   * Classification: *Preflight support package*
   * Action: **Retire** (preflight support package).

7. **`kk-video-c9f99fee6146-r2-preflight`**
   * Worker: `colab-0b9f491b-1673` | Age: 136.36 hours
   * Classification: *Preflight support package*
   * Action: **Retire** (preflight support package).

8. **`kk-video-c9f99fee6146-preflight`**
   * Worker: `colab-8e078e8a-46874` | Age: 152.63 hours
   * Classification: *Preflight support package*
   * Action: **Retire** (preflight support package).

9. **`ltx-probe-77f`**
   * Worker: `colab-b92f3be2-6230` | Age: 212.33 hours
   * Classification: *Probe package*
   * Action: **Retire** (old probe package).

---

## 3. Reconciliation Execution Steps

Per procedure requirements:
1. **Durable Record**: Write an audit log entry referencing this plan prior to executing state modifications.
2. **Claim Removal vs. Retirement**:
   * All 14 stale claims identified in the current report are historical probes, preflights, or variant/one-off exploratory storyboard shots rather than active canonical final-cut production render packages.
   * Therefore, execute **Retirement** (marking them `retired` with reason and preserving original claim metadata and artifacts in history) rather than requeuing them, to prevent unintended automatic reruns of obsolete probes and preflights.
3. **Canonical Render Rule Enforced**:
   * Ensure any future re-enqueuing of production packages strictly adheres to the active project render manifest (`manifest_version`, `approved_shots`, `source_hash`, `renderer/model`, `output_root`, `qc_contract`).
   * Probes, preflights, and old variants remain excluded from final cut promotion.

---

## 4. Operational Guardrails & Verification

* **Read-Only / Safety Check**: Status scans remain strictly read-only. Stale cleanup is explicit, auditable, and logged.
* **Concurrency Limits**:
  * MLX concurrency = 1 (enforced on Mac Studio / local runner)
  * Colab concurrency = 1 managed runner
  * One writer per queue
* **No Unapproved Actions**: As mandated by runner rails, this artifact plan is emitted without releasing claims, deleting files, starting renders, or mutating cards.
