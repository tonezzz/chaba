# Concrete Dispatcher Implementation Plan (OPS-1042 / video-render-dispatcher-plan-repair)

## 1. Executive Summary & Objective

This implementation plan defines the production-ready architecture, operational reconciliation workflow, and safety controls for the video render dispatcher. Operating under **OPS-1042**, the dispatcher governs claim lifecycles, queue hygiene, storage tiers, and canonical manifest adherence across Google Drive video roots (`ada-nest-kk-mac-video-pilot` and `ada-nest`). 

The primary objective is to transition the video queue from an unmanaged, stale-claim state into a deterministic, audit-trailed, single-writer pipeline where stale claims are cleanly reconciled, canonical manifests dictate active execution, and historical assets are preserved without accidental overwrites or orphan dispatches.

---

## 2. Queue Status & Baseline Inventory Analysis

Analysis of the current queue status report (`reports/video-queue-status-2026-11-03.json`) reveals:
- **Total Queues Monitored:** 2 (`gdrive:ada-nest-kk-mac-video-pilot`, `gdrive:ada-nest`)
- **Active Claims:** 0 across all queues (no live workers currently holding active unexpired locks).
- **Stale Claims:** 14 total stale claims exceeding the 2-hour lease TTL:
  - *ada-nest-kk-mac-video-pilot:* 5 stale claims ranging from 76.98 to 107.3 hours old (originating from Mac Studio workers and legacy probe IPs).
  - *ada-nest:* 9 stale claims ranging from 126.3 to 251.51 hours old (originating from Colab runners and Mac Studio test preflights).
- **Completed / Artifact Packages:** 23 total (`done` states: 9 in pilot, 14 in nest).

### Root Cause of Stale Accumulation
Ephemeral runners (Colab instances and test sessions) and terminated Mac Studio processes frequently abandon their leases without sending explicit release heartbeats or cleanup signals, leaving stale `.claim` markers behind in Google Drive roots.

---

## 3. Canonical Manifest & Sacred Father Reference

Per the **Sacred Father canonical manifest** (`reports/sacred-father-canonical-manifest-20261103.yml`), the active single source of truth for the primary video project is:
- **Project ID:** `kk-video-c9f99fee6146`
- **Manifest Version:** `final-preview-v4-clean`
- **Source Hash:** `5a6ef65431865b1b4957b70023d3e83cbdcaf19a5ebaa4896c6f2cd31ad06d34`
- **Renderer Engine:** `ltx-mlx` (Model: `ltxv-2b-0.9.8-distilled` on `kk-mac`)
- **Deliverable Path:** `gdrive:ada-nest-kk-mac-video-pilot/final/pdf-final-preview-v4-clean.mp4`
- **QC Status:** Passed (720 frames, 59.92s duration, AAC audio, private preview gating).

**Enforcement Rule:** Only packages and shots matching this canonical manifest may be dispatched or requeued. Probes, old preflights (`-r2-preflight`, `-r3-preflight`, `-r4-preflight`), and unapproved variants are strictly prohibited from active execution and must be retired or archived.

---

## 4. Video Claim Lifecycle Procedure (OPS-1042)

Every video package adheres strictly to the 6 lifecycle states:
1. **`queued`**: Valid package waiting in queue with no claim and no done/failed marker.
2. **`running`**: Fresh claim owned by a live, heartbeating worker (Lease TTL: 2 hours).
3. **`stale`**: Claim older than 2 hours without active worker heartbeat evidence.
4. **`done`**: Durable artifact present in Drive with a verified completion marker.
5. **`failed`**: Terminal failure recorded with diagnostic error logs.
6. **`retired`**: Intentionally removed from dispatch queues without deleting history.

### Heartbeat Contract
Active workers must write and refresh a heartbeat every 15 minutes containing:
- `project_id`
- `package`
- `worker` (hostname/PID or container ID)
- `pid/job_id`
- `phase`
- `started_at`
- `heartbeat_at`

---

## 5. Step-by-Step Reconciliation & Stale Claim Remediation Plan

To clear the 14 stale claims safely without violating data integrity or retention rules:

### Step 1: Immutable Pre-Reconciliation Audit
Generate a pre-execution audit ledger snapshot recording the exact file paths, claim metadata, timestamps, and worker signatures for all 14 stale claims. Store this audit record under `reports/audit/reconciliation-20261103.json`.

### Step 2: Categorization & Triage
1. **Completed / Artifact Packages:** For packages already possessing verified `done` markers and Drive artifacts (e.g., `kk-video-c9f99fee6146-source-image-use-approved` or prior finalized variants), close out their history ledger entries. **Never rerun automatically.**
2. **Stale Probes & Ephemeral Preflights:** For old Colab preflight packages (`kk-video-c9f99fee6146-*-preflight`) and ltx probes (`ltx-probe-*`), write a durable `retired` marker containing the retirement reason (expired ephemeral run) and preserve their records in cold storage/history.
3. **Stale Canonical Packages:** For legitimate stalled workflow packages matching the current canonical manifest:
   - Remove **only** the stale `.claim` marker file from Google Drive.
   - Leave the package manifest, source hashes, and intermediate assets strictly intact.
   - Re-enter the package into `queued` state so the single approved worker pool can reclaim it.

### Step 3: Concurrency & Single-Writer Guardrails
- Enforce **one writer per queue** via strict filesystem/Drive locking (`/tmp/video-dispatcher.lock`).
- Enforce **one video runner per host** (MLX concurrency = 1 on KK-Mac; 1 managed runner on Colab).
- Ensure all status scans remain strictly read-only (`--dry-run` default).

---

## 6. Video History & Data Management Governance

Following `docs/kb/video-history-data-management-procedure.md`:

### Data Separation Classes
- **`source`**: Original PDF, source images, rights notes, source SHA-256 (`5a6ef654...`).
- **`plan`**: Briefs, story beats, shot lists, prompt packs, asset manifests.
- **`derived`**: Crops, embeddings, cached model weights, intermediate frames.
- **`review`**: Labeled clips, contact sheets, QC reports, reviewer notes (never published directly as final public cuts).
- **`deliverable`**: Silent previews, narrated previews, subtitle files (`.th.srt`, `.en.srt`), final MP4 cut.
- **`execution`**: `pack.yml`, manifests, execution logs, verifiers, done/failed markers.

### Storage Tiers & Retention
- **Hot / Local**: Active model caches, current render work, current QC staging.
- **Warm / Drive**: Manifests, sources, approved review artifacts, final cuts (`gdrive:ada-nest-kk-mac-video-pilot/final/`), and audit reports.
- **Cold / Archive**: Superseded renders, obsolete probes, reproducible intermediates.
- **Retention Rule**: Never delete original PDFs, approved final cuts, project manifests, or QC/verdict records without explicit owner sign-off. Safe cleanup is restricted to failed temporary renders, duplicate downloads, and unreferenced extracted frames after reference verification.

---

## 7. Metrics, Verification & Success Criteria

The dispatcher run is deemed successful only when it satisfies all operational metrics:
1. **Stale Claim Count:** Trend to `0` (all 14 stale claims successfully reconciled into `done`, `retired`, or safely released back to `queued`).
2. **Fresh Claim Latency:** < 5 minutes from queue insertion to verified worker claim.
3. **Orphan / Duplicate Rate:** 0% duplicate claim attempts (enforced by atomic claim file creation).
4. **Artifact Pass Rate:** 100% of promoted deliverables pass audio/video decode checks and match canonical SHA-256 signatures.
5. **Human Guardrails:** Zero unapproved auto-promotions, zero board-api mutations during plan-only runs, and strict adherence to the Sacred Father manifest.
