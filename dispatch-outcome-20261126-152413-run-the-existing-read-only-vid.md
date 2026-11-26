# Dispatch outcome — video queue read-only audit (2026-11-26)

Card: `video-queue-audit-opencode` — retry of the 2026-11-03 opencode attempt
that failed verification (artifact path was gitignored; re-queued 2026-11-26
to the `reports/card-runner/` path).

## What was done

- Ran `scripts/devnest/video_queue_status.py` (read-only, stale TTL 2h)
  against both video roots: `gdrive:ada-nest/kk-mac-video-pilot` and
  `gdrive:ada-nest`. No claims released, no Drive writes, no renders.
- Re-verified the Sacred Father canonical manifest artifacts live via
  `scripts/devnest/video_dispatch.py verify` (read-only QC).
- Diffed every pack state against `reports/video-queue-status-2026-11-24.json`.

## Result

- Pilot root: 14 packs — 11 done, 1 queued
  (`kk-mac-mlx-colab-scene0-control-20261124`), 2 failed (terminal
  shot03-oneoff v1/v2, superseded by done v3).
- ada-nest root: 79 packs — 60 done, 19 queued (doc-v2 chain x6,
  `kk-video-c9f99fee6146-preview-v2`, 12 support/eval packs incl. a loose
  `T4-QUEUE-ADDITIONS.md`).
- Claims: **0 active, 0 stale** on live packs; 39 residual claim files on
  done packs aged 492–812h (~20–34 days) — cosmetic residue, not blockers.
- State delta vs 2026-11-24: **zero** — queues fully idle ~48h.
- Sacred Father (`kk-video-c9f99fee6146`): canonical final-preview
  artifacts re-verified `qc_pass=true` (mp4 + th/en srt on pilot `final/`).
  `pdf-final-preview-canonical-v1.mp4` remains an unmanifested alternate —
  canonical-or-stray decision still open for Tony/KK.

## Deliverables (all committed in this worktree)

- `reports/card-runner/video-queue-status-opencode.md` — declared card
  artifact: counts, stale-claim ages, canonical manifest status,
  recommended safe next actions.
- `reports/video-queue-status-2026-11-26.json` — machine-readable inventory.
- `docs/ssot/jobs/devnest/2026-11-26-video-queue-audit.yml` — job trail.
- This file.

## Recommended safe next actions (from the report)

1. Nothing to release — no live/stale claims exist.
2. Role-triage the 20 queued packs: retire the 12 support/eval packs +
   loose file; promote `doc-v2-*` and `preview-v2` only via an approved
   `video-dispatch/v1` manifest.
3. `kk-mac-mlx-controls.yml` scene0: KK visual review → `approved:true` →
   `video_dispatch.py apply`.
4. Optional approved hygiene: clean/retire the 39 residual claim files;
   re-publish the corrected canonical manifest to Drive `manifests/`
   (still stale paths since 2026-11-24).
5. Decide `pdf-final-preview-canonical-v1.mp4` status.

## How to verify

```
python3 scripts/devnest/video_queue_status.py        # exit 0, JSON inventory
python3 scripts/devnest/video_dispatch.py verify \
  --manifest scripts/devnest/video-manifests/sacred-father-final-preview.yml
# -> "verified": true, qc_pass: true on all 3 artifacts
```

lessons:
- The card's declared artifact path must be committed, not just written — reports/* is gitignored; reports/card-runner/ is the exempt dir (root cause of the 2026-11-03 verifier fail).
- video_queue_status.py takes ~4-5 min: one recursive rclone lsf per root plus one rclone lsl per claim file (~40 residual claims on done packs each cost a call).
- video_dispatch.py verify/plan are read-only and safe to run for canonical-manifest QC; apply is the only mutating subcommand and is gated on approved:true.
- Residual claim files on done/failed packs are reported separately (residual_claims) and must not be treated as stale work — the tool already excludes them from state classification.
