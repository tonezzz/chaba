# Dispatch outcome — session-capture-c1-spec (OPS-1355)

Card: `session-capture-c1-spec` — "Session capture C.1: router/harvester contract spec (SSOT)".
Branch: `dispatch/20261125-094612-goal-define-capture-router-har`, commit `f518fa092a` (not pushed, per dispatch rules).

## What changed

- `docs/ssot/ssot.knowledge-capture.yml` (+144 lines): two new sections after "Phase D Baseline":
  - **Capture Router Contract (Phase C.1)** (`layout: list`, 8 items): scope/posture, event envelope (candidate -> proposal), approved sinks and actions, dedupe key, audit metadata, idempotency, dry-run default, guards.
  - **Capture Router Contract — Examples** (`layout: text`): real router-output proposals, ledger `entries:`/`applied:` shapes, and a dry-run gate sketch.
  - `config.last_updated` bumped to 2026-11-25.
- `docs/ssot/CHANGELOG.md`: 2026-11-25 minor entry per `ssot.file-control.yml` change workflow.
- `docs/ssot/jobs/kanban/2026-11-25-session-capture-c1-contract-spec.yml`: job record (goal, verify steps, method notes).

## Grounding decisions

The contract documents the **as-built** Phase C slice rather than inventing new vocabulary: identity is `(source, source_id)`; `dedupe_key = "<sink>:<native_key>"`; sink namespace = the 7 Capture Matrix rows; the only write-approved pair is `(kanban, create)` via `capture-apply.py` -> board-api (OPS-0024); router/harvester are read-only propose-first. A prior session's PR #218 draft (`ada/session-capture-c1-spec`, commit `bcc7c68176`) had a lighter 28-line section with an invented `event_id`/UUID envelope, no approved-sinks enumeration, no dedupe-key derivation, and no examples — this dispatch supersedes it. Card comms and job record both note this.

## Result vs acceptance

- "SSOT section reviewed/merged" — section written and committed on the dispatch branch; merge is the dispatcher's governed step (card comms posted with outcome + location). PR #218 should be closed/superseded on merge.
- "examples" — included (proposal JSON x2, ledger YAML, dry-run sketch), verified against actual `capture-router.py` output.
- "validation passes" — `ssot-validate-all.mjs`: 6425 files, 0 errors (file now over bloat *review* thresholds — warnings only, expected for a contract spec); `ssot-prose-smell.py`: 0 flags; structural check (title/icon/layout/items, no dup labels): clean; `capture-router.py --self-test` 13/13, `harvester.py --self-test` 5/5.

## How to verify

```
python3 -c "import yaml; yaml.safe_load(open('docs/ssot/ssot.knowledge-capture.yml'))"
python3 scripts/ssot-prose-smell.py --file docs/ssot/ssot.knowledge-capture.yml
node scripts/ssot-validate-all.mjs   # ~64s, all files
git show f518fa092a --stat
```

## lessons:

- Card comms may reveal a prior session already drafted the work (here PR #218 on `ada/session-capture-c1-spec`): check `git branch -a` + card comms before re-implementing; supersede with a grounded version rather than duplicate.
- board-api `/comment` intermittently returns `{"error":"board write lock saturated — retry","retry_after_s":5}` — retry after ~5-6s, it succeeds.
- `scripts/ssot-validate-all.mjs` validates all ~6400 SSOT YAMLs (~64s); for fast iteration do a targeted yaml.safe_load + section/item structural check first.
- `capture-router.py` has a hyphen — `harvester.py` imports it via importlib by path; don't try `import capture_router` style imports in new code.
- Dispatch worktrees: commit to the dispatch branch only — no push, no merge; the dispatcher lands it.
