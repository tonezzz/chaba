# Dispatch outcome — video-render-dispatcher (OPS-1042)

Card: `video-render-dispatcher` — implement a read-only inventory/status layer
first, then a controlled dispatcher for project `kk-video-c9f99fee6146`
(Sacred Father) and future video projects. No push/commit to default branch;
work stayed in this worktree on the dispatch branch.

## What changed

### Read-only inventory layer (rewritten)
`scripts/devnest/video_queue_status.py` — now inventories **every** pack under
each queue root (nothing filtered out), classifies on two axes:

- **state** (vocabulary from `docs/kb/video-queue-claim-lifecycle-procedure.md`):
  `done` > `failed` > `retired` > claims > `queued`; a fresh claim (<2h TTL)
  reports `running`, an expired one `stale`; terminal packs carrying residual
  claims are counted separately in `residual_claims`.
- **kind**: `render` vs `support` via a broadened VIDEO name regex.

Per-pack `pack_detail` lists markers, claims, and artifact paths. Strictly
read-only — never claims/releases/mutates. rclone resolved via `shutil.which`
or `~/.local/bin/rclone` (fleet PATH gotcha).

### Controlled dispatcher (new)
`scripts/devnest/video_dispatch.py` (~570 lines) — `plan` / `apply` / `verify`
subcommands driven by manifest YAML in `scripts/devnest/video-manifests/`:

- `plan`: for each stage reports `skip-queued`/`skip-done`/`would-apply` +
  routing decision. Declared-state stages never rerun ("manifest declares
  state — never rerun").
- `apply`: refuses unless `manifest.approved: true`; staging gate requires
  pack.yml to declare runner + artifacts; `inputs:` fetches declared store
  inputs with sha256 verification and `rclone purge` rollback on failure;
  KK-Mac admission via `kk_mac_admission.snapshot` (heartbeat <900s,
  disk ≥20GB, load ≤4.0, temp ≤60C, idle) — Colab only after complete
  staging.
- `verify`: per-stage artifact QC (glob patterns, exists/size); honest
  `qc_pass: false` until artifacts land.

### Manifests
- `scripts/devnest/video-manifests/sacred-father-final-preview.yml` — the
  canonical final-preview manifest (deliverable).
- `scripts/devnest/video-manifests/kk-mac-mlx-controls.yml` — 3 stages:
  `colab-scene0-control` (already queued → plan reports `skip-queued`),
  `colab-scene1` (deferred; 3 embed .pt inputs with live-verified sha256s),
  `vimax-goldenhour-s0` (deferred).

### Reports / docs
- `reports/video-queue-status-2026-11-24.json` — fresh live audit
  (force-added; `reports/*` is gitignored but the 11-03 report was tracked).
- `reports/sacred-father-canonical-manifest-20261103.yml` — artifact roots
  corrected (`gdrive:ada-nest-kk-mac-video-pilot` → real
  `gdrive:ada-nest/kk-mac-video-pilot`), `verified:` block added with
  live sha256/ffprobe of `pdf-final-preview-v4-clean.mp4`
  (2,497,219 B, `9a0e3722…`, h264 640x384, 720f, 59.92s, AAC); unmanifested
  `pdf-final-preview-canonical-v1.mp4` alternate recorded for owner review.
- `docs/ssot/jobs/devnest/2026-11-24-video-render-dispatcher.yml` — trail doc.

## Live audit findings (2026-11-24)

- `gdrive:ada-nest/kk-mac-video-pilot`: 14 packs — 11 done, 1 queued
  (`kk-mac-mlx-colab-scene0-control-20261124`), 2 failed; 0 active claims,
  2 residual stale claims on done support packs.
- `gdrive:ada-nest`: 79 packs — 30 render / 49 support; 60 done, 19 queued;
  0 active claims, 37 residual stale claims all on terminal packs.
- **Naming gotcha:** spec's `gdrive:ada-nest-kk-mac-video-pilot` does not
  exist; real rclone path is `gdrive:ada-nest/kk-mac-video-pilot`.
- KK-Mac gate at test time: `eligible: false` (`load_high`, load_1m 4.18 >
  4.0); heartbeat fresh (118s), disk 57GB free — dispatcher correctly holds
  MLX stages rather than routing to Colab without full staging.

## Verification

- `python3 -m py_compile` clean on both scripts; `video_queue_status.py`
  ran live against both remotes producing the JSON report.
- `video_dispatch.py plan` / `verify` smoke-tested against both manifests —
  correct `skip-queued`/`absent`/`qc_pass:false` reporting.
- `apply` correctly refused the unapproved manifest (exit non-zero, no
  mutation).
- `queue_states()` unit-checked on the pilot remote: 14 packs →
  11 done / 1 queued / 2 failed, matching the status report.

## How to verify

```bash
python3 scripts/devnest/video_queue_status.py            # live read-only audit
python3 scripts/devnest/video_dispatch.py plan scripts/devnest/video-manifests/sacred-father-final-preview.yml
python3 scripts/devnest/video_dispatch.py verify scripts/devnest/video-manifests/kk-mac-mlx-controls.yml
```

## Not done / follow-ups

- No stage was applied — `apply` is gated on `manifest.approved: true` and
  KK-Mac admission currently fails on load. First real dispatch needs an
  approved manifest + awake/eligible KK-Mac (or fully staged Colab batch).
- Residual stale claims on terminal packs (39 across both queues) are
  cosmetic — reconciliation per claim-lifecycle procedure is a separate
  approved write op, not done here (read-only mandate).
- `gdrive:ada-nest/kk-mac-video-pilot/manifests/` copy of the canonical
  manifest still carries old artifact paths — needs re-publish on next
  approved write.

lessons:
- rclone remote path gotcha: spec `gdrive:ada-nest-kk-mac-video-pilot` is
  wrong — real path is `gdrive:ada-nest/kk-mac-video-pilot`; always
  `rclone lsd` before trusting a spec'd remote root.
- `rclone lsf --format pt` emits `path/;UTC-timestamp` (trailing slash on
  dirs, no fractional/offset) — parse with `strptime("%Y-%m-%d %H:%M:%S")`
  as UTC, and strip trailing `/` before splitting rel paths.
- Claim files are single-level `claim/<worker>` — check
  `rel.startswith("claim/") and rel[6:]`, NOT a second `/` in the worker
  name (that silently misses every claim).
- `reports/*` is gitignored — queue status reports must be `git add -f`'d
  to stay durable (precedent: video-queue-status-2026-11-03.json).
- `video_dispatch.py verify` exits non-zero until artifacts exist — that
  is honest QC, not a bug; plan/verify are safe to run anytime, apply is
  the only mutating subcommand and requires `approved: true`.
