# dispatch outcome — repo-work-two-parts-1-generate (ada-tools-command-reference, attempt 4)

## What changed

Both card deliverables landed in this worktree (commit `0c4ef525d3`, on a
base rebased to origin/master — the attempt-3 failure was a checkpoint
blocked by the single-writer hook on a 13-behind worktree):

- `scripts/ada/tools-commands-catalog.py` — generator. AST-parses
  ada-voice `backend/realtime_provider.py` (builtin + `CHABA_DECLARATIONS`
  guest layer) and `backend/tools.d/*.py` + `manifest.yml`; joins
  `tool_guide.yml`, `tool_runner/common.py::_ALIASES` (AnnAssign-aware),
  `ssot.tool-surface.yml` merge families/schema tier/coverage debt,
  `tests/scenarios-live/*` utterances (real trigger phrases), chaba
  `docs/ssot/infrastructure/ssot.tools.yml` (canonical backend per
  ada-voice surface name), and `git blame --porcelain` spans for
  last-changed. Writes both outputs; `--check` diffs committed outputs
  ignoring the volatile Generated/generated_at fields (drift gate).
- `docs/kb/ada-tools-commands.md` — generated catalog, do-not-edit +
  managed block: 37 builtin · 31 drop-in · 3 guest tools with
  purpose/triggers/backend/cost-policy/last-changed; merge-family table
  (26 families, all `merged`), 92-alias absorbed-name surface, drift
  notes (0 unregistered tools; 1 stale registry surface `host_status`;
  guide entry for undeclared `ada_board_write`).
- `docs/kb/ada-tools-commands.json` — `schema:1` machine snapshot; the
  verb's only data source.
- `docs/kb/ada-tools-verb-contract.md` — part-2 contract: producer/
  consumer split, snapshot field contract, deterministic answer
  template (<50 ms, never computes live), failure modes (missing
  snapshot → ok:false, never fabricate), wiring checklist.
- `tests/ada/test_tools_commands_catalog.py` — 5 tests on a scratch
  ada-voice tree: layers/counts, join fields, aliases/family status,
  render + `--check` roundtrip, tamper detection. All pass.
- Filed follow-up card `ada-capabilities-verb-wiring` (ADA-0020, backlog,
  executor=devin) — the ada-voice consumer + deploy-time snapshot
  transport, per the contract's wiring checklist.

## Result

DONE-CONDITION met: `docs/kb/ada-tools-commands.md` generated and
reviewable; verb contract documented; wiring card filed.

Note: idc02's ada-voice checkout is 7 commits behind origin/main (HEAD
`6a39e3a`, 2026-11-19) — the doc flags it; regen after a pull refreshes
counts/dates. The 103-tool census era is over: post-consolidation the
live surface is 71 tools + 92 absorbed aliases.

## Verify

```
python3 scripts/ada/tools-commands-catalog.py           # regen
python3 scripts/ada/tools-commands-catalog.py --check   # -> "up to date"
python3 -m pytest tests/ada/test_tools_commands_catalog.py -x -q  # 5 passed
```

ADA_VOICE_REPO/ADA_PI_REPO overrides the ada-voice checkout path
(default `<repo-parent>/ada-voice`).

lessons:
- git blame --porcelain prints full headers only on a commit's FIRST block — key committer-time by sha, or continuation lines resolve to epoch 0 (1970-01-01).
- `_ALIASES` in tool_runner/common.py is an AnnAssign, not Assign — AST parsers must handle both.
- Prior attempt died at checkpoint (single-writer hook, 13-behind worktree): rebase to origin/master and commit early; a dirty worktree + failed checkpoint = lost work.
- ada-voice realtime_provider builtin decls are dict literals inside _builtin_declarations() — an Assign-name-only parse (the old stub's DECLARATION pattern) misses ~34 of 37.
- scenario turns carry real trigger utterances (turns[].user + expect.calls) — deterministic trigger phrases, no hand curation needed.
