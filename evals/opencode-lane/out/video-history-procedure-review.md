# Video History Procedure & Lifecycle Review Report

## 1. Executive Summary
This review evaluates `docs/kb/video-history-data-management-procedure.md` in conjunction with the system's Artifact Lifecycle SSOT (`docs/ssot/ssot.artifact-lifecycle.yml`) and Kanban Claim Lifecycle rules (`docs/ssot/kanban/ssot.kanban.yml`). The procedure provides a robust data-management taxonomy for PDF-to-video pipelines (source, plan, derived, review, deliverable, execution), strict lineage tracking, and tiering (hot/warm/cold). However, gaps remain in operationalizing artifact aging, claim reconciliation during multi-host runner failures, and deterministic retention enforcement.

---

## 2. Document & Lifecycle Findings

### A. Data-Management & Lineage (`docs/kb/video-history-data-management-procedure.md`)
- **Strengths:** Clear immutable project IDs, rigorous artifact metadata tracking (source hash, model/revision, prompt pack hash, seed, renderer commit), and explicit non-destructive correction rules (`review`, `v2`, `final-v1` via `supersedes`/`parent_artifact`).
- **Gaps:**
  - Lacks explicit integration with the repository's Artifact Lifecycle SSOT (`ssot.artifact-lifecycle.yml`) states (`active`, `stale`, `superseded`, `archived`, `retracted_expired`).
  - Storage tier transition criteria (hot $\to$ warm $\to$ cold) are descriptive rather than automated. There is no automated garbage collection rule for intermediate derived frames or stale model caches beyond manual KK-Mac hygiene.

### B. Artifact Lifecycle Alignment (`docs/ssot/ssot.artifact-lifecycle.yml`)
- **Standards:** The SSOT mandates that handwritten content is never deleted (tombstoned or archived only), whereas regenerable generated artifacts (such as intermediate frames or temporary video renders) can be pruned.
- **Application to Video History:** Temporary derived frames, embeddings, and unreferenced staging caches qualify as regenerable generated artifacts and can be safely purged once downstream review and deliverable artifacts are verified and pushed to warm/cold storage (Google Drive).

### C. Claim & Execution Lifecycle (`docs/ssot/kanban/ssot.kanban.yml`)
- **Standards:** Enforces atomic first-wins claims, checkout exclusivity, session timeouts (>3d claimed with no comms = stale claim/reclaimable), and runner eligibility gates.
- **Application to Video History Pipelines:** Video generation jobs running across distributed nodes (e.g., KK-Mac local MLX, Colab GPU packs, idc02/idc03 runners) frequently encounter lease timeouts or runtime interruptions. The procedure currently assumes persistent worker sessions without specifying how stale claims or orphaned execution locks (`done`/`failed` markers) are reclaimed or audited.

---

## 3. Recommended Procedure Enhancements

1. **Formalize Lifecycle State Mapping:**
   Update `docs/kb/video-history-data-management-procedure.md` to explicitly cross-reference `docs/ssot/ssot.artifact-lifecycle.yml` states:
   - *Active:* Current render work, active model cache.
   - *Stale:* Intermediate frames past freshness retention thresholds.
   - *Superceded:* Prior render variants (`v1` replaced by `v2`) marked with tombstone metadata.
   - *Archived:* Cold/archive Drive paths for reproducible intermediates.

2. **Define Automated Pruning Rules for Derived Data:**
   Specify that derived non-final artifacts (e.g., intermediate frames, unreferenced model caches) may be automatically reaped after final deliverable verification and Drive sync, adhering to the "delete-only-generated" rule in `ssot.artifact-lifecycle.yml`.

3. **Incorporate Claim Stale-Check and Reclaim Protocols:**
   Add explicit guidance for handling interrupted video rendering jobs (e.g., Colab runtimes or local MLX packs where queue leases expire or heartbeat signals fail), aligning with Kanban claim timeout policies (>3d stale claim reclamation).
