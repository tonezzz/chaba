# Dispatch outcome — video-queue-audit-opencode-repair

## What was done

Ran `scripts/devnest/video_queue_status.py` read-only on idc02 against
both video roots (`gdrive:ada-nest/kk-mac-video-pilot` and
`gdrive:ada-nest`, stale TTL 2.0h) and wrote the declared artifact
`reports/card-runner/video-queue-status-opencode.md` plus the raw JSON
evidence `reports/card-runner/video-queue-status-opencode-20261126.json`.
Committed on the dispatch branch (b96264d8d8); not pushed.

## Findings

- 93 packages total: 71 done, 20 queued, 2 failed; **0 running, 0
  stale claims** — the 2026-11 stale-claim cleanup held; queue fully
  idle, zero drift vs the 2026-11-24 audit.
- 39 residual claim files on `done` packs, ages 492–812h (median ~780h)
  — cosmetic residue, each costs an rclone RTT; recommended a separate
  explicit cleanup pass, not done here (read-only scope).
- Sacred Father (`kk-video-c9f99fee6146`, 12 packs on ada-nest): 11 done
  (7 with done+retired markers), `-preview-v2` queued but deliberately
  held per Tony (missing `-resume-authorized` gate pack). Canonical
  `pdf-final-preview-v4-clean.mp4` verified live on Drive — 2,497,219
  bytes matching the 2026-11-24 sha256-verified manifest record.
- 2 failed pilot packs (shot03-oneoff, -v2) superseded by done v3 —
  retired-marker candidates.
- Report includes safe recommendations: doc-v2-* dispatch ordering,
  pilot stray packs need owner call, support-pack triage, lifecycle-doc
  root-path fix.

## How to verify

- `git show b96264d8d8 --stat` — two files under `reports/card-runner/`
  (gitignore-exempt dir, the prior verifier failure cause).
- Re-run `python3 scripts/devnest/video_queue_status.py` on any host
  with the `gdrive:` rclone remote.
- `rclone lsl gdrive:ada-nest/kk-mac-video-pilot/final/` for the
  canonical artifact spot-check.

lessons:
- video_queue_status.py issues one `rclone lsl` per claim file — with 39 residual claims the run took ~7 min; batch-stat claims (`lsl` on the claim/ dir) if it gets slower.
- `docs/kb/video-queue-claim-lifecycle-procedure.md` still lists the nonexistent root `gdrive:ada-nest-kk-mac-video-pilot`; the real path is `gdrive:ada-nest/kk-mac-video-pilot`.
- `reports/card-runner/` is the gitignore-exempt report dir — declaring artifacts under bare `reports/` fails the opencode verifier every time.
- Sacred Father `-preview-v2` looks queued but is intentionally held via a missing `requires:` gate pack (`-resume-authorized`); queue presence ≠ dispatchable.
