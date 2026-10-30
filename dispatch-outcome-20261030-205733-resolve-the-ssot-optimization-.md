# Dispatch outcome — resolve SSOT optimization warning for kk-video-preview-output-qc-assembly

Card: `ssot-bloat-kk-video-preview-qc-card` · 2026-10-30 · worktree `dispatch-wt-20261030-205733-…`

## Decision

**Narrow reviewed exemption, not a structural split.** The card
(`docs/ssot/kanban/cards/kk-video-preview-output-qc-assembly.yml`, 497 lines)
is `column: done` + `auto_close`d; ~480 of those lines are `comms` (71) +
`requests` (7, all answered). Splitting was rejected on three independent
grounds:

- **Comms trim is unsafe** — `merge_cards` (reconcile-local-conflicts /
  merge-card-yaml) unions comms on (at|ts, from, text) and deletions do not
  propagate; any diverged copy resurrects trimmed entries on merge.
- **Whole-card archive is unsafe now** — `cards/archive/` per
  `ssot.kanban.yml` column_sla is for done >30d; this card is ~1d old and
  still receives board-api `/comment` writes (lesson upsert logged
  2026-10-30 20:12). `card_path` globs `cards/*.yml` non-recursively, so an
  archived card becomes unwritable (`no card <id>`).
- **Sidecar history file is unsupported** — no consumer follows a history
  pointer; under `cards/` it renders as a phantom card, outside it loses
  the merge driver and every board consumer.

## Changes

- `docs/ssot/ssot.file-optimization.yml` — added
  `kanban/cards/kk-video-preview-output-qc-assembly.yml` to
  `config.bloat_exemptions.review_threshold` with an inline comment
  (rationale, expiry condition, owner). Review threshold only — the
  750-line hard cap still applies.
- `docs/ssot/jobs/kanban/2026-10-30-kk-video-card-bloat-exemption.yml` —
  new decision record (why-not-split analysis, scope, follow-up owner =
  board ops / kanban-archive sweep, revisit when the card qualifies for
  `cards/archive/`).
- `docs/ssot/focus-inbox/2026-10-29-2000-…-ssot-optimization.yml` —
  `status: draft → processed` with `processed_reason` pointing at the
  record.
- **Not changed**: the card file itself, card status/action semantics,
  comms history, `reports/SSOT_OPTIMIZATION_WARNINGS.json` (baseline left
  untouched — served checkout's kanban-commit owns that generated file and
  drops the stale entry on its next cycle; committing it here would risk a
  mid-air conflict and an unreviewed baseline refresh).

## Verification

- `node scripts/ssot-optimize.mjs` — regenerated reports; the kk-video
  bloat warning is **absent** (exemption honored).
- `node scripts/ssot-optimize-gate.mjs` — kk-video no longer flagged; the
  **only** new-debt item is unrelated drift: active review card
  `kanban/cards/kk-mac-local-llm-lane.yml` crossed 350 tonight (~356,
  still receiving board-api writes). Left as-is — it is live debt the
  baseline machinery absorbs, or it needs its own review; flagging it on
  the task card.
- `node scripts/ssot-validate-all.mjs` — 3383 files, 0 errors; all three
  touched files `✅ Valid`.
- `python3 scripts/ssot-validate-refs.py` — 3388 files parsed, no broken
  refs.
- `python3 -m unittest discover -s tests/board` — 312 tests, 2 errors,
  both `OSError: Disk quota exceeded` writing test state under /tmp
  (environmental, unrelated to the change).
- `python3 scripts/board/merge-card-yaml.py --selftest` — OK.
- `python3 scripts/render-board.py` — 1130 cards rendered; the card
  renders `column: done` with all 71 comms intact (generated
  `stacks/web/public/apps/board/*` reverted afterwards).

## How to verify

On master after merge: `node scripts/ssot-optimize.mjs &&
node scripts/ssot-optimize-gate.mjs` — the kk-video warning should be gone
from `reports/SSOT_OPTIMIZATION_WARNINGS.json` and the gate should not
list it. Once the served checkout's kanban-commit next commits a
regenerated baseline, PR #62 rebased onto master should pass
`Fail on warnings absent from baseline` (kk-mac drift absorbed by the
same cycle or needs its own review).
