# Video queue audit — 2026-11-26 (read-only)

Card: `video-queue-audit-opencode` · Tool: `scripts/devnest/video_queue_status.py`
(stale TTL 2h) · Dispatcher QC: `scripts/devnest/video_dispatch.py verify`
Mode: strictly read-only — no claims released, no Drive writes, no renders started.

Machine-readable evidence: `reports/video-queue-status-2026-11-26.json`
Job trail: `docs/ssot/jobs/devnest/2026-11-26-video-queue-audit.yml`

## Queue counts

| Root | Packages | Render | Support | done | queued | running | stale | failed | retired |
|---|---|---|---|---|---|---|---|---|---|
| `gdrive:ada-nest/kk-mac-video-pilot` | 14 | 12 | 2 | 11 | 1 | 0 | 0 | 2 | 0 |
| `gdrive:ada-nest` | 79 | 30 | 49 | 60 | 19 | 0 | 0 | 0 | 0 |
| **Total** | **93** | **42** | **51** | **71** | **20** | **0** | **0** | **2** | **0** |

State diff vs `reports/video-queue-status-2026-11-24.json`: **zero changes** —
no packs added/removed, no state transitions, no new claims in ~48h. The
queues are completely idle.

## Stale claims

- Live stale claims: **0**. Live active (running) claims: **0**.
- Residual claim files on terminal (done) packs: **39** — not stale work,
  just claim-file residue. Ages 492.5h–811.8h (~20.5–33.8 days), all on
  `done` packs; per the claim-lifecycle procedure these are history, not
  dispatch blockers.
- Oldest residual: `gdrive:ada-nest/scout-thai-tts` (worker
  tony-dell-3383232, ~810.9h). Newest: `bge-hybrid-shadow-idc03-v2`
  (~492.5h).

## Queued packs (20 — none claimed, none blocked on a live worker)

Pilot root (1): `kk-mac-mlx-colab-scene0-control-20261124` — MLX lane
control pack, gated on KK visual review + `kk-mac-mlx-controls.yml`
`approved:true` before any dispatch.

ada-nest root (19):
- doc-v2 chain (6 render): `doc-v2-{delivery,music-bed,rerender-shots,shot-qc,subs,vo-earcheck}`
- Sacred Father preview (1 render): `kk-video-c9f99fee6146-preview-v2`
- probes/support (12): `kk-mac-video-probes`, `gaussian-splat-*` x4,
  `kk-mac-gaussian-*` x2, `img-gen-bench-t4`, `jev-triage`,
  `devnest-model-slot-30m`, `decision-arena`, `T4-QUEUE-ADDITIONS.md`
  (loose file, not a pack dir)

Failed (terminal, never rerun): `kk-mac-storyboard-i2v-shot03-oneoff-20261030`
and `-v2-20261030` on the pilot root — superseded by `-v3` (done).

## Canonical Sacred Father packages

Project `kk-video-c9f99fee6146`. Canonical manifest:
`reports/sacred-father-canonical-manifest-20261103.yml`; dispatch manifest:
`scripts/devnest/video-manifests/sacred-father-final-preview.yml`
(`approved: false`, record-only — nothing left to dispatch).

`video_dispatch.py verify` re-run today: **qc_pass=true** — all three
canonical artifacts present on `gdrive:ada-nest/kk-mac-video-pilot/final/`:
`pdf-final-preview-v4-clean.mp4` (1 match), `.th.srt`, `.en.srt`.

Sacred Father pack coverage across both roots: 11 `kk-video-c9f99fee6146-*`
packs on ada-nest (9 done — embeds, image-conditioning-probe,
pdf-image-audit, pdf-text-diff, preflight/r2/r3/r4 [retired], preview,
source-image-use-approved [retired], voice-clone-probe; **1 queued**:
`preview-v2`) + the `kk-mac-storyboard-*`/`docpilot-v3` render packs on the
pilot root that fed the canonical cut.

Open item carried from 2026-11-24: `final/pdf-final-preview-canonical-v1.mp4`
(2026-11-04 alternate encode, PSNR~14dB vs v4-clean) still sits unmanifested
on the same `final/` root — canonical-or-stray decision is Tony/KK's.

## Recommended safe next actions

1. **Nothing to release** — zero live or stale claims; do not touch claims.
2. **Role-triage the 20 queued packs** (lifecycle procedure step: every
   queued package needs a declared role). Candidates for `retired` markers:
   the 12 support/eval packs and the loose `T4-QUEUE-ADDITIONS.md`.
   Candidates for manifest promotion: `doc-v2-*` chain and
   `c9f99fee6146-preview-v2` — only via an approved `video-dispatch/v1`
   manifest, never ad-hoc.
3. **scene0 control**: KK visual review → flip `kk-mac-mlx-controls.yml`
   `approved:true` → `video_dispatch.py apply` (a dispatch action, gated).
4. **Optional hygiene** (needs approval — Drive mutation): clean or
   `retired`-mark the 39 residual claim files on done packs; re-publish the
   corrected canonical manifest to `kk-mac-video-pilot/manifests/` (still
   stale paths per the 11-24 job record).
5. **Decide** `pdf-final-preview-canonical-v1.mp4` status (canonical cut vs
   stray) — owner visual review.
6. Optional: schedule `video_queue_status.py` as a read-only job once the
   format settles (follow-up already noted 2026-11-24).

## Verification

- `python3 scripts/devnest/video_queue_status.py` → exit 0, JSON above.
- `python3 scripts/devnest/video_dispatch.py verify --manifest
  scripts/devnest/video-manifests/sacred-father-final-preview.yml` →
  `verified: true`, `qc_pass: true` on all 3 artifacts.
- State diff vs 2026-11-24 report: empty (no pack added/removed/transitioned).
