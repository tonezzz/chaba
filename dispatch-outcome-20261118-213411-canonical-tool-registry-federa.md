# Dispatch outcome — agent-tool-registry-federation-ee0089 (Phase 1, second lane)

## What happened

A prior dispatch on the same card (`dispatch/20261118-205815-canonical-tool-registry-federa`,
worktree `dispatch-wt-20261118-205815-*`) had already completed Phase 1 and pushed
its branch; this session was spawned afterward on a fresh worktree. Rather than
redoing the inventory, this lane **ported the finished work** by cherry-picking
the core commit `e9ac59d97e` onto this branch (`96c57f951d`) and re-verified it
here. Content is identical to the reviewed prior-branch version.

## What changed on this branch

- **`docs/ssot/infrastructure/ssot.tools.yml`** (new, 1,619 lines) — canonical
  agent tool registry: 111 rows (89 `kind:tool` + 22 `kind:provider`) covering
  all four existing registries (tools.d manifest 31, realtime_provider builtins
  37 + 3 guest re-decls, ada_mcp.py 26, devin mcp_config.json 21). Each row has
  domain-namespaced `name`, condensed `sig`/`req`, `policy` tier
  (read|confirmed|owner_only|mixed + `secondary` for tools.d's
  secondary_allowed), `backend`, `transport`
  (native-decl|stdio-mcp|http), `agents` lanes, and per-lane `surfaces` names.
  `inventory:` section records sources, dupes (memory.search,
  wiki.extensions, media.adobe_stock_qc, board.* overlap) and gaps
  (board.plan/preflight family ada-ocb-only; mcp.colab name collision).
- **`docs/kb/agent-tool-federation.md`** (new) — design note: registry →
  per-surface generators (ada-voice decls/manifest, opencode.json mcp block,
  devin mcp_config + wrappers); policy enforced at service layer (board-api
  doors, tool_runner gate sets, ada_mcp token gates); 4-phase migration order.
- **`docs/ssot/ssot.index.yml`** — registry indexed in both System &
  Environment sections.
- **`docs/ssot/ssot.file-optimization.yml`** — `infrastructure/ssot.tools.yml`
  added to `bloat_exemptions.hard_threshold` (flat catalog >750 lines by design).

## Verification

- `node scripts/ssot-validate-all.mjs`: 5,048 files, **0 errors**;
  `infrastructure/ssot.tools.yml` ✅ Valid, no warnings.
- Cherry-pick applied with no conflicts — surrounding base identical to prior
  branch.

## Boundaries kept

No live service changes, no pushes, no edits outside the worktree, no secrets
in SSOT. Phase 2+ (ada_mcp thin-adapter rewrite, MCP session-dir race fix, T2
read-only opencode additions) left for the follow-up cards per spec.

## Note for merge-sweep

The same deliverables exist on both
`dispatch/20261118-205815-canonical-tool-registry-federa` (pushed) and this
branch — identical file contents, so whichever merges first wins cleanly and
the second is a no-op on those paths.
