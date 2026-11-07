# Task: backup freshness survey

Read the declared backup roots in
`evals/shadow/task/inputs/backup-roots.json` and produce
`evals/shadow/task/artifacts/backup-freshness.json`.

## Rules

- Read-only. Only the artifact file may be written. No commits/pushes.
- Relative `path` values resolve against the repo worktree you stand in.
- An absent root is `exists:false` — recorded, NOT counted as stale.

## Method

For each root: does it exist? If yes, find the newest file anywhere
beneath it (by mtime), record `newest_file` (relative path),
`newest_mtime` (ISO-8601), `age_hours` (float, now minus mtime),
`fresh` = age_hours <= that root's `fresh_hours`. Bound the walk —
skip `.git`, cap at 200k entries.

## Required JSON fields

- `host`, `collected_at`
- `roots` — `[{path, label, exists, newest_file, newest_mtime, age_hours, fresh}]`
- `stale_roots` — labels of existing-but-stale roots
- `verdict` — `pass` when no existing root is stale, else `fail`
- `read_only` — must be `true`
