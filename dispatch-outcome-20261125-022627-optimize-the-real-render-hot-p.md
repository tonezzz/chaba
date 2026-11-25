# Dispatch outcome — render-board-real-cost-git-subprocesses

Card: `render-board-real-cost-git-subprocesses` (KNB-0165)
Branch: `dispatch/20261125-022627-optimize-the-real-render-hot-p` (2 commits, not pushed)
Host: mn01

## What the card asked vs what was already there

The spec's two hot paths were measured 2026-11-17 (idc03 13.5s /
tony-omen 2m8s / idc02 11.4s). PR #197 (`8c1e3b1d27`, merged
2026-11-24) had already landed the first half of each fix:

- `yaml.CSafeLoader` when libyaml exists (`_YAML_LOADER`)
- `git branch --merged origin/master` batch for the ancestry check +
  tip-keyed on-disk `git cherry` cache (10s-bounded, 24h negative TTL)

So this dispatch implemented the *remaining* delta:

## Changes (committed on the dispatch branch)

`scripts/render-board.py`
- `_all_dispatch_refs()`: ONE `git for-each-ref
  --format='%(refname:short) %(objectname)' refs/heads/dispatch/`
  yields every (branch, tip) pair. It feeds `_run_branches()`' slug
  index AND `_branch_tip()` — `_branch_merged` no longer spawns a
  per-branch `git rev-parse`, and `git cherry` now evaluates the tip
  sha (consistent even if the branch moves/is deleted mid-render).
  Steady-state git cost per render: 2 subprocesses total
  (for-each-ref + lazy branch --merged) + cherry only on cache misses.
- `_load_card_file()` + `_flush_cards_cache()`: stat-keyed
  (size, mtime_ns) pickle cache at
  `docs/ssot/kanban/.render-cards-cache.pkl` (gitignored, format v1,
  atomic tmp+rename write, atexit backstop, exists()-pruned). Same
  stat invariant `dir_hash` already relies on for `--if-changed` —
  writers land via atomic rename/git checkout, both bump mtime.
  Callers receive shallow copies so `checks` chips can't poison the
  cached parse; non-dict YAML still normalizes to `{id: stem}`.

`scripts/render-board2.py`
- The archive loop (1176 extra YAML parses per render) now shares
  `_rb._load_card_file`, with an explicit `_rb._flush_cards_cache()`
  before `compute_checks` mutates card dicts.

`.gitignore`: + `.render-cards-cache.pkl[.tmp]`

Trail: `docs/ssot/jobs/board/2026-11-25-render-board-card-parse-cache.yml`

## Measured (mn01, libyaml host; 754 live + 1176 archive cards)

| render | before | after (warm) |
|---|---|---|
| render-board.py | 2.68–2.90s | 1.25–1.39s (~50%) |
| render-board2.py | 4.49–4.77s | 1.57–1.68s (~65%) |

Cold first run ~3.2s builds the ~13–23MB cache once; subsequent
renders pay ~0.1–0.3s pickle load + parse only changed files. On
libyaml-less hosts (the omen 43s case) the same cache turns ~40s+ of
pure-Python YAML into a sub-second pickle load — the portable fix the
spec offered as the alternative to CSafeLoader.

## Verification

- Byte-identical outputs vs pre-change baseline (stash → render →
  unstash → render → diff): `board/cards.json`, `board2/cards.json`,
  `board2/archive.json`, `classic.html`, both `index.html` — all
  identical modulo the `generated` timestamp.
- `_branch_merged` spot-checked against `git merge-base
  --is-ancestor` ground truth on a 12-branch sample: 0 mismatches.
- Cache invalidation verified: content+mtime change → re-parse;
  restore → re-parse; outputs unchanged.
- `python3 -m py_compile` clean; SSOT validation passed on the jobs
  yml (pre-commit hook).

## Notable finding (carded as KNB-1366)

`compute_checks`' git path is currently **dead code**: zero live cards
carry `action.task_id` (runner-agent era — ids live in runner
`state.json`; done cards only embed the slug inside
`action.result`'s `devin-task-<slug>.service` text, and `claim.session`
is empty). The code-merged / per-run outcome chips cannot fire today.
Follow-up card `render-board-checks-task-id-dead-path` filed via
board-api asking whether to recover the slug from `action.result`,
use merge-sweep's `task_id_for` fallbacks, or delete the machinery.

## How to verify after merge

```
python3 scripts/render-board.py     # ~1.3s warm on mn01-class host
python3 scripts/render-board2.py    # ~1.6s warm
# first run per checkout builds docs/ssot/kanban/.render-cards-cache.pkl
```

lessons:
- Card-brief measurements age fast: #197 landed the spec's first-half fixes a day before this dispatch; always `git log -S` the target functions before re-implementing.
- `git stash -u` on a worktree whose .gitignore edit is itself stashed makes ignored artifacts (the new .pkl) briefly visible as untracked — harmless, but check `git stash show --include-untracked` before assuming.
- YAML plain scalars can't contain ": " — jobs/SSOT yml entries with `name: value` lines need `>-` folded blocks (two scanner errors to learn it).
- render-board2 parses cards/archive/*.yml (1176 files) inline — any card-parse optimization must cover it too; it now shares `_load_card_file`.
- board-api runs render-board.py with NO --if-changed on every mutation, so full-render cost is paid per card write — persistent cross-process caches (pickle on disk) are the lever, not in-process memoization.
