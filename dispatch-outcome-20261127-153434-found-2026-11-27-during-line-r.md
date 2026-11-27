# Dispatch outcome — yomi-update-conversations-missing-imports

## What changed

`scripts/yomi/update-conversations.mjs` — added three missing names to the
existing named import from `./summary-utils.mjs` (lines 12–14):

- `validateAndTruncateContext`
- `getContextLengthStatus`
- `LLAMA_REQUEST_TIMEOUT`

Import-only change, matching the reference ordering already used by
`scripts/yomi/process-conversations.mjs`. No logic changes. Committed as
`5b03c5b82ed` on branch `dispatch/20261127-153434-found-2026-11-27-during-line-r`.

## Root cause (confirmed)

The script called all three symbols (usage sites now at lines 563–564,
591, 623, 869–870, 897, 936, 1005–1006, 1040, 1079) but never imported them,
so every summary path threw `validateAndTruncateContext is not defined`
after `retryWithBackoff` exhausted 3 retries — while conversation/message
writes still succeeded and the process exited 0.

## Verification done

- `node --check scripts/yomi/update-conversations.mjs` → SYNTAX OK
- `grep` confirms all three names appear in the import block and every
  usage site now resolves
- Dynamic import of `summary-utils.mjs` confirms all three exports exist
  (`function`, `function`, `number`)
- `git diff` is exactly +3 lines in the import block — nothing else touched

## Not yet verified (requires merge + deploy)

The live `yomi-update-all` job on idc03 runs from the served checkout
`~/CascadeProjects/chaba-tony-dell` (systemd ExecStart). This dispatch
cannot push, so the fix reaches idc03 only after this branch merges and the
served checkout pulls (kanban-commit / chaba-repo-sync cadence). After that,
trigger or wait for a `yomi-update-all` run and confirm summaries are
produced with no `is not defined` errors in the journal.

## Lessons

- Node ESM named imports fail at module-eval time only for missing *exports*;
  using an imported-but-undeclared identifier throws ReferenceError at call
  time — `node --check` alone won't catch it. A quick static cross-check of
  identifiers vs. the import block (or `eslint no-undef`) catches this class.
- `process.argv[1] === import.meta.url` guard made the file import-safe to
  reason about, but top-level `await client.connect(transport)` (line ~153)
  means a real `import()` smoke test would spawn the yomi MCP stdio server —
  don't do it casually on a workstation.
