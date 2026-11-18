# Dispatch outcome — agent-tool-registry-federation-ee0089 (Phase 1)

## What changed

- **`docs/ssot/infrastructure/ssot.tools.yml`** (new, 1,619 lines) — canonical
  agent tool registry: 111 rows (89 `kind:tool` + 22 `kind:provider`) covering
  every inventoried tool across all four existing registries, each with
  domain-namespaced name, condensed signature (`sig`/`req`), policy tier
  (`read|confirmed|owner_only|mixed` + `secondary` mirroring tools.d
  `secondary_allowed`), backend service, transport
  (`native-decl|stdio-mcp|http`), allowed agent lanes, and per-lane surface
  names. Dupes folded into single canonical rows with both surface bindings
  (`memory.search`, `wiki.extensions`, `media.adobe_stock_qc`); gaps and the
  `mcp.colab`/`mcp.colab_upstream` name collision recorded in `inventory.gaps`.
- **`docs/kb/agent-tool-federation.md`** (new) — design note: registry →
  per-surface generators (ada-voice decls/manifest, opencode.json mcp block,
  devin mcp_config + wrappers, future lanes); policy enforced at service layer
  (board-api doors + tool_runner gate sets + bridge token gates); 4-phase
  migration order.
- **`docs/ssot/ssot.index.yml`** — registered the new file in both
  System & Environment index sections.
- **`docs/ssot/ssot.file-optimization.yml`** — added
  `infrastructure/ssot.tools.yml` to `bloat_exemptions.hard_threshold`
  (a flat catalog is inherently >750 lines).

## Inventory result

| Source | Count | Notes |
|---|---|---|
| tools.d manifest + DECLARATION/TOOL | 31 | `ada_adobe_stock` uses `TOOL` not `DECLARATION` — generator must handle both |
| realtime_provider builtins | 36 + camera + 3 guest re-decls | guest variants bound via `ada-voice-guest` lane (CHABA_ALLOW subset) |
| opencode/ada_mcp.py | 26 | stdio FastMCP `ada-control`; reimplements board/mddb/wiki — phase-2 target |
| devin mcp_config.json | 21 | 20 active + google-home disabled |

Key findings: `board.plan`/`preflight`/`dev.start_check`/`dev.dispatch_check`
exist only on ada-ocb (gap for ada-voice); devin reaches `board.*` only via
raw board-api HTTP; wiki/adobe-stock/memory-search are implemented twice.

## Verification

- `node scripts/ssot-validate-all.mjs` (npm run check:ssot): 5,042 files,
  0 errors; `infrastructure/ssot.tools.yml` ✅ Valid, no warnings.
- `python3 scripts/ssot-prose-smell.py`: 0 flagged scalars.
- Pre-commit hooks (YAML, hostname compliance, required fields, optimize
  gate) all passed on commit `e9ac59d97e` — branch
  `dispatch/20261118-205815-canonical-tool-registry-federa`, not pushed.

## Boundaries kept

No live service changes, no edits outside this worktree, no pushes, no
secrets copied into SSOT (token-in-URL providers reference config paths
only). Phase-2 items (thin-adapter rewrite of ada_mcp.py, MCP session-dir
race fix, T2 read-only opencode additions) left for follow-up cards.
