# Dispatch outcome — ssot-baseline-board-drift-race (attempt 2)

## What changed

Implemented option (a) from the card spec: `kanban/cards/` is now excluded
from the advisory review-threshold bloat check (350 lines / 10 sections /
45 items) in `scripts/ssot-validate-all.mjs`. The 750-line hard threshold,
hard-section/item caps, and `bloat_exemptions` grandfathering are unchanged
and still gate — a card crossing 750 lines still produces a fresh warning
that fails `ssot-optimize-gate` until baselined.

Files (commit `41986aec99` on `dispatch/20261125-044950-observed-2026-11-24-after-pr-2`):

- `scripts/ssot-validate-all.mjs` — review-threshold block skips
  `rel.startswith('kanban/cards/')` (+7/-1 lines in the generated Python).
- `docs/ssot/ssot.file-optimization.yml` — comment documenting the
  validator-level card exemption; the two existing per-card
  `review_threshold` entries kept for the record.
- `reports/SSOT_OPTIMIZATION_WARNINGS.json` — baseline refreshed via full
  `node scripts/ssot-optimize.mjs` (the sanctioned escape; shrinks the
  baseline by ~1000 lines of stale card review warnings and absorbs 10
  fresh non-bloat warnings that drifted in since the last refresh).
- `docs/ssot/jobs/kanban/2026-11-25-ssot-baseline-board-drift-race.yml` —
  decision/rationale trail.

## Verification (done condition)

- Simulated a >350-line card write: temp 426-line card under
  `kanban/cards/` produced **0 warnings** (previously a review-threshold
  bloat warning → gate red). Card deleted after the run.
- Hard threshold still blocks: `timer-alert-idc03-kanban-dispatch.yml`
  (3824 lines) still emits `Bloat: 3824 lines exceeds hard threshold of
  750`; `devin-session-audit-2026-10-29.yml` at 751 lines surfaced as a
  fresh gated warning during verification.
- Full CI path: `node scripts/ssot-optimize.mjs` +
  `node scripts/ssot-optimize-gate.mjs` → `139 warning(s), all covered by
  baseline`, exit 0. Full `ssot-validate-all.mjs` → 6474 files, 0 errors.

## Notes / residual risk

- Card **data-isolation** warnings (IPs/secrets in comms) and **kanban
  request-shape nudges** remain gated — deliberately; they signal real
  hygiene issues, not line-count drift. If they prove noisy they need
  their own card.
- ~77 cards already exceed the 750-line hard cap (baselined debt); the
  trim/archive sweep for them is unchanged open work.
- Prior attempt (tony-macbook) died on a runner unit-not-found before
  doing any work — nothing was repeated.

## How to verify

```
node scripts/ssot-validate-all.mjs docs/ssot/kanban/cards/<any 350-750 line card>
# -> 0 warnings
git show HEAD --stat   # commit 41986aec99
node scripts/ssot-optimize-gate.mjs   # after staging refreshed baseline: exit 0
```

lessons:
- ssot-optimize.mjs's dev-system step rewrites docs/ssot/ssot.dev-system.assessment.yml with host-local stats — revert it before committing from a dispatch worktree.
- ssot-optimize-gate resolves the baseline from the git index first (`:file`), so `git add reports/SSOT_OPTIMIZATION_WARNINGS.json` is enough to verify green locally before commit.
- The validator's whole-file cache is keyed on the script's own sha256 — editing ssot-validate-all.mjs forces a full ~6500-file revalidation (took ~4min here, fine in background).
