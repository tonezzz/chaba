# Dispatch outcome — deploy-ada-stagger-verify

## What changed

Card `deploy-ada-stagger-verify`: `scripts/deploy-ada.sh` in the
**ada-voice** repo (not this chaba worktree — the card's own job doc
notes the fix lives there). Created dedicated worktree
`~/CascadeProjects/ada-voice-wt-deploy-ada-stagger-verify` on branch
`dispatch/deploy-ada-stagger-verify` (1 commit `acfd766` ahead of
`origin/main` `8a31a71`; NOT pushed — dispatch rails).

Diff (`scripts/deploy-ada.sh` section 5 only; drain section untouched):

- Removed the fixed `sleep 2` + single-pass `is-active --quiet` check
  that false-failed units sitting in `activating (start-pre)` during
  the ~110s fleet stagger (ExecStartPre=ada-start-stagger.sh offsets;
  the 2026-11-18 exit-7 false-fails on 36828b1/a2a2026).
- New poll loop, tunable via `ADA_VERIFY_S` (default 180s): `active` →
  pass; `failed` → fast-fail; any other state (`activating`,
  `inactive`, `deactivating`, empty) → still in flight, re-poll every
  3s until the deadline. After the deadline each pending unit gets one
  final `is-active` read and FAILs with its observed state if not
  active. `inactive` deliberately waits — a queued start job can
  briefly report it mid-transaction.
- Header env docs gained `ADA_VERIFY_S`.

Job trail: `docs/ssot/jobs/ada/2026-11-25-deploy-ada-stagger-verify.yml`
in the same ada-voice worktree/commit.

## Verification

No live deploy run (would touch prod units). Instead the new verify
block was extracted verbatim and exercised under a stubbed
`systemctl --user is-active` (per-unit mode files in /tmp):

- stagger→active: polls logged `waiting on:`, exits 0, prints
  `active:` per unit — done-when case 1.
- one `failed` unit: fast-fail message, exit 1 — done-when case 2.
- unit stuck `activating` with `ADA_VERIFY_S=5`: deadline FAIL with
  state, exit 1.
- `bash -n` clean (no shellcheck on host).

## How to verify / next steps

1. Review/merge `dispatch/deploy-ada-stagger-verify` in ada-voice
   (tony-dell edit point), or push the branch first.
2. Install on idc03 per AGENTS.md:
   `install -m 0755 scripts/deploy-ada.sh ~/.local/bin/deploy-ada.sh`
   (self-drift gate will refuse the stale installed copy otherwise).
3. Next real deploy during a staggered restart should exit 0 with all
   `active:` lines; a crashed unit still exits nonzero.

Residual noted in the job file: `systemctl --user restart` itself is
unchanged and still hard-fails under `set -e`; the RCA attributed exit
7 to the verify path, but if restart ever returns nonzero while units
recover, that path needs the same poll treatment.

lessons:
- The card lives in the chaba kanban but the fix target was the ada-voice repo — check the card's job docs for the real edit point; precedent is a dedicated `ada-voice-wt-*` worktree + `dispatch/*` branch, never the live checkout.
- ada-voice `deploy-ada.sh` verify must treat `activating (start-pre)` as in-flight, not failed — idc03 stagger offsets run ~110s (stagger.conf TimeoutStartSec=180).
- `is-active` during a fleet restart can briefly report `inactive` for a queued start job — don't fast-fail on it; only `failed` is definitive.
