# Dispatch outcome — precommit-warning-baseline

Shipped card option (a): the committed `reports/SSOT_OPTIMIZATION_WARNINGS.json`
is now the known-warnings baseline, and the commit-time SSOT gate fails only on
warnings absent from it — new debt. Known debt no longer blocks merge commits or
dispatch-branch landings, so `--no-verify` and foreign-host commits are no longer
needed for that reason.

## Changes (commit 46f8fcc on dispatch/20261007-231022-options-a-baseline-file-report)

- `scripts/ssot-optimize-gate.mjs` (new) — compares the freshly generated
  warnings file against the baseline (staged blob first, so a commit can carry
  warnings + baseline update together; else HEAD; missing baseline = advisory
  pass). Warning text is digit-normalized for matching, so a known warning
  whose counts drift ("404 lines" vs "400 lines") is not treated as new debt.
- `.husky/pre-commit` — the `METRICS > 0 → fail` block replaced by a call to
  the gate; the hook now snapshots the baseline file's state before the
  optimizer rewrites it and restores it afterwards (index / HEAD / delete
  scratch) so the tree doesn't stay perpetually dirty.
- `.gitignore` — `reports/` → `reports/*` + `!reports/SSOT_OPTIMIZATION_WARNINGS.json`
  (dir-level ignore can't be negated inside; file stages with plain `git add`).
- `reports/SSOT_OPTIMIZATION_WARNINGS.json` — seeded from a FULL
  `ssot-optimize.mjs` run on `origin/master` (bc172cc, via a scratch worktree),
  not this 126-commits-behind branch, so the landing merge doesn't trip on
  master's current warnings.
- `.github/workflows/ssot.yml` — "Verify no warnings" now runs the same gate
  (log-reference issues still hard-fail). This also un-reds the workflow, which
  was failing on every docs/ssot push since the bloat warning appeared.
- `docs/ssot/infrastructure/ssot.quality.yml` — ci.ssot-optimize entry updated.
- `docs/ssot/jobs/infrastructure/2026-10-07-precommit-warning-baseline.yml` —
  decision/runbook trail (why (a) over (b): the inbox-ack path is hardcoded to
  the served checkout, so it's host-dependent — wrong in worktrees and other
  hosts).
- Card moved to `done` with a comms entry.

## How to silence a warning going forward

```
node scripts/ssot-optimize.mjs          # full run — do NOT use --staged
git add reports/SSOT_OPTIMIZATION_WARNINGS.json
git commit                              # baseline diff is the audit trail
```

## Verified

- `bash .husky/pre-commit` with clean SSOT staged → pass.
- Staging a new SSOT file producing warnings → hook fails, listing exactly the
  new warnings.
- Staging `kanban/ssot.kanban.yml` (baselined bloat warning) → pass; warnings
  file restored clean in the worktree afterwards.
- Baseline resolves from index (covers HEAD since index holds tracked blobs);
  a staged baseline update is honored in the same commit.

## Found while here (flagged on the card, not fixed)

- `docs/ssot/jobs/reports/2026-10-07-hosting-provider-intl.yml` and
  `docs/ssot/jobs/yt-dub/2026-10-06-yt-voice-dub-cuefit.yml` have REAL YAML
  syntax errors on master (plain scalars swallowing `key:` lines) — likely
  committed by the kanban auto-committer outside the hook. Baselined as known
  debt; worth a follow-up fix card.
- Every `ssot-optimize.mjs` run rewrites `docs/ssot/ssot.dev-system.assessment.yml`
  with the local checkout's metrics (pre-existing side effect).

## Note

hooksPath is not armed in this dispatch worktree, so the hook was verified by
invoking `bash .husky/pre-commit` directly (identical to how git runs it). The
new gate takes effect everywhere `scripts/install-hooks.sh` has armed
`.husky` — including the served checkout where the original failure occurred.
