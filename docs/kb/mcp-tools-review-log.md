---
category: operations
---

# MCP Tools Review Log

Track usage, fallback decisions, and policy updates for `ssot.mcp-tools.yml`.

## 2026-08-15 — activated
- Promoted `ssot.mcp-tools.yml` to `active`.
- Added rule pointers to global rules, `chaba/.windsurfrules`, `trade/AGENTS.md`.
- SSOT validation: 49 files, 0 errors.

## 2026-08-15 — rule optimization
- Concern: full `ssot.mcp-tools.yml` reads cost ~2,300 tokens each.
- Updated global rules, `chaba/.windsurfrules`, `trade/AGENTS.md` to use `ssot-search` or `grep` for the relevant `policy.<domain>` section only.
- Expected result: per-call read drops to ~20-50 tokens.
- Future metric: track how often full SSOT reads still happen.

## 2026-08-15 — ssot/kb sync and assessment
- Added targeted-read step to `ssot.mcp-tools.yml` `selection_workflow`.
- Validated `ssot.mcp-tools.yml` YAML syntax.
- Assessed all SSOT files by size. Other large files (>5KB) are not referenced by per-call rules, so no further rule changes needed.
- General pattern: use `ssot-search`/`grep` for any rule that points to an SSOT larger than ~3KB.

## Entry format

- Date:
- MCP used:
- Expected primary:
- Fallback used (if any):
- Issue or exception:
- Proposed SSOT change:
