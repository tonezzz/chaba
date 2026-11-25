# Dispatch outcome — session-capture-c1-spec (OPS-1355), attempt 2

Card: `session-capture-c1-spec` — "Session capture C.1: router/harvester contract spec (SSOT)".
Branch: `dispatch/20261125-122319-goal-define-capture-router-har`.

## Finding: the reported failure was a false negative — the work already landed

Attempt 1 (09:46) committed `f518fa092a`, chaba pushed the branch and
auto-merged it at 10:07 as **merge `8277cd3e` → origin/master**. Tony's
11:20 verify note ("No code landed in origin/master from this card") is
factually wrong: `git merge-base --is-ancestor 8277cd3e origin/master`
confirms the merge, and its stat shows all four deliverables:

- `docs/ssot/ssot.knowledge-capture.yml` (+144): **Capture Router Contract
  (Phase C.1)** — event envelope (candidate→proposal), approved sinks and
  write-approved posture, dedupe_key format, audit metadata, idempotency,
  dry-run default, guards — plus **Capture Router Contract — Examples**
  (4 worked examples: 2 proposals, ledger shape, dry-run sketch).
- `docs/ssot/CHANGELOG.md` (+8): 2026-11-25 minor entry.
- `docs/ssot/jobs/kanban/2026-11-25-session-capture-c1-contract-spec.yml`:
  attempt-1 job record.
- `dispatch-outcome-20261125-094612-goal-define-capture-router-har.md`.

The 10:09 merge-sweep GC'd the attempt-1 worktree and the session ended
with a transient systemd error; whatever the verify pass sampled, it did
not include merge ancestry.

## What this attempt changed

- `docs/ssot/jobs/kanban/2026-11-25-session-capture-c1-spec-verify.yml`:
  job record documenting the verification pass and the false-negative
  root cause.
- Closed **PR #218** (`ada/session-capture-c1-spec`, the superseded
  +28-line draft with an invented event_id/UUID envelope) with an
  explanatory comment — it can no longer conflict with the merged contract.
- No changes to `ssot.knowledge-capture.yml` — re-verified it is complete
  and accurate as merged.

## Acceptance re-verification (all pass)

- **SSOT section reviewed/merged** — present on origin/master via 8277cd3e.
- **Examples** — Examples section exists; live `capture-router.py` output
  reproduces the documented proposals *exactly* (same fields, dedupe_keys
  `kanban:ada-capture-hooks` / `kanban:04e0aa363440`, actions link/create,
  confidence 0.88/0.8).
- **Validation passes** — `node scripts/ssot-validate-all.mjs`: 6479 files,
  0 errors (139 warnings repo-wide; the file's bloat review-threshold
  warnings are expected, documented in the c1 job record);
  `ssot-prose-smell.py`: 0 flagged; `capture-router.py --self-test` 13/13;
  YAML parses, 12 sections, no duplicate titles.

## How to verify

```
git merge-base --is-ancestor 8277cd3e origin/master   # exit 0
grep -n "Capture Router Contract" docs/ssot/ssot.knowledge-capture.yml
python3 scripts/chaba/capture-router.py --self-test   # 13/13
echo '{"source":"focus-inbox","source_id":"2026-11-12-wiki-login","text":"Fix the Google button label on the wiki login page","as_of":"2026-11-12","already_filed":false}' | python3 scripts/chaba/capture-router.py --input -
node scripts/ssot-validate-all.mjs                    # ~66s, 0 errors
```

## lessons:

- Verify-queue/merge-sweep false negative: a dispatch branch auto-merged then worktree-GC'd reads as "no deliverable" — always check `git merge-base --is-ancestor <merge> origin/master` before declaring work lost.
- `node scripts/ssot-validate-all.mjs --help` still runs the full 6479-file validation (~66s) and caches to `.cache/` (gitignored) — don't bother with flags.
- `capture-router.py` contract examples are reproducible verbatim via `--input -` JSON — cheap way to prove spec-vs-code grounding.
- Superseded PRs from earlier sessions on the same card (here #218's lighter draft) should be closed with a pointer to the merged commit, not left open to conflict.
