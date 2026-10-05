# dispatch-outcome — kanban-commit-single-writer

## Decision
Picked **option (a)**: `chaba-tony-dell` stays the only checkout with a
periodic auto-committer (kanban-commit.timer). Option (b)'s mechanics were
kept but folded *inside* the single writer, because the verify clause
requires `pull --rebase` to survive an untracked collision — the exact stall
in the card note. Multi-checkout auto-committers were the bug source;
spreading jittered writers would not fix it structurally.

## What changed
- `scripts/git-safe-pull.sh` (new) — shared `git pull --rebase --autostash`
  hardening: resolves untracked paths colliding with incoming upstream files
  *before* the pull (identical → dropped; different → renamed aside as
  `<name>.local-<ts>`), resolves mid-rebase conflicts under generated paths
  upstream-wins (local side preserved as `.local-conflict-<ts>`), handles
  autostash-pop conflicts, verifies upstream is in HEAD.
- `scripts/board/kanban-commit.sh` — scoped add now also sweeps
  `docs/ssot/focus-inbox/` (stray served-checkout findings get persisted);
  pull goes through git-safe-pull; push retries 3x with jitter.
- `.husky/pre-commit` — warn-only single-writer block: committing
  `docs/ssot/focus-inbox/` outside the served checkout warns it won't be
  swept; >N-commit divergence (default 10, `CHABA_DIVERGENCE_N`) warns to
  rebase. Node validations now guarded by script existence so the warnings
  work in checkouts without `npm install`.
- `scripts/install-hooks.sh` (new) — arms the hook via `core.hooksPath`
  (`.husky/_` if husky installed, else `.husky`) + sets `pull.rebase` /
  `rebase.autoStash`. `--all` covers every `~/CascadeProjects/chaba*`.
- `scripts/check-single-writer.sh` (new) — drift lint: uncommitted
  focus-inbox files, divergence >N, missing hooksPath per checkout.
- `scripts/audits/gh-runs-watch.py` — `git_commit_push` now safe-pulls
  before each of 3 push attempts; previously a bare non-ff push failure
  stranded alert commits in the `chaba` checkout forever.
- `systemd/kanban-commit.timer` — `RandomizedDelaySec=120`.
- `docs/ssot/jobs/kanban/2026-10-05-kanban-commit-single-writer.yml` —
  decision record + rollout steps.
- `AGENTS.md` — one-line pointer under Chaba memory.
- Drive-by fix: `docs/ssot/jobs/infrastructure/2026-10-05-precleanup-unmerged-guard.yml`
  had a broken YAML scalar (`": "` inside a list item) failing repo-wide
  SSOT validation; fixed.

## Result
`bash tests/test-kanban-commit.sh` → **22/22 checks pass** (self-contained
bare-origin + two clones): two parallel writers both land; untracked
collision (different content) completes `pull --rebase` unattended with the
local copy preserved aside; identical collision absorbed silently; hook
warns outside served checkout and stays silent inside it; lint flags
drift. `ssot-validate-all.mjs` → 1189 files, 0 errors.

## How to verify / rollout
1. `bash tests/test-kanban-commit.sh`
2. After merge: reinstall `kanban-commit.timer` for the jitter, then run
   `scripts/install-hooks.sh --all` once on tony-dell to arm warnings in
   every chaba checkout.
3. `scripts/check-single-writer.sh` anytime to audit drift.
