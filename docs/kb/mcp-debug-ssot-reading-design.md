# Design: mcp-debug SSOT registry reading support

## Context

`mcp-debug` already exposes SSOT tools in `scripts/mcp_debug/ssot.py`:

- `mcp_read_ssot(path, limit)` — read one SSOT file from the repo.
- `mcp_search_ssot(query, collection, limit)` — search SSOT documents (MDDB first, local fallback).
- `mcp_query_ssot(query, path, key, limit)` — resolve an SSOT document and return a dotted/integer key.
- `mcp_mddb_doc(query, ...)` — full MDDB-backed document fetch.
- `mcp_ssot_append(...)` — append a line/block to an SSOT file.

The registry was recently split into per-type partition files under `docs/ssot/ssot.registry.*.yml`. The main `docs/ssot/ssot.registry.yml` is now a lightweight index of partitions.

## Problem

The current tools are document-oriented, not asset-oriented. Looking up a single project asset (e.g. "what is the path, host, and port for the Helm Dashboard?") requires:

1. Knowing which partition the asset lives in.
2. Reading that partition with `mcp_read_ssot` or `mcp_query_ssot`.
3. Scanning the `assets` list client-side.

There is no single call that resolves an asset by `id`, `name`, `path`, or `type` across all registry partitions.

## Goal

Add registry-aware lookup to `mcp-debug` so MCP consumers can resolve a project asset in one call, and fetch its source SSOT in a second call if needed.

## Proposed design

Add one new tool and one helper, keep existing tools unchanged.

### 1. `mcp_registry_lookup` tool

**Input schema:**

```json
{
  "host": "tony_omen",
  "q": "helm",
  "type": "ssot",
  "by": "any",
  "limit": 5
}
```

- `host`: target host (for routing; the registry is read from that host's repo).
- `q`: keyword/id/name/path fragment.
- `type`: optional filter (`ssot`, `script`, `service`, `timer`, `stack`, `h3-app`).
- `by`: search fields — `any` (default), `id`, `name`, `path`, `label`.
- `limit`: max results.

**Output contract:**

```json
{
  "ok": true,
  "q": "helm",
  "results": [
    {
      "id": "helm",
      "name": "ssot.apps.helm.yml",
      "type": "ssot",
      "path": "docs/ssot/apps/ssot.apps.helm.yml",
      "project": "chaba",
      "purpose": "...",
      "status": "active",
      "tags": ["helm", "apps"],
      "registry_file": "docs/ssot/ssot.registry.ssot-apps.yml"
    }
  ]
}
```

### 2. `mcp_registry_get` tool

Convenience wrapper that takes `id` or `path` and returns the full asset metadata plus the content of its source SSOT (or an excerpt).

**Input schema:**

```json
{
  "host": "tony_omen",
  "id": "helm"
}
```

**Output contract:**

```json
{
  "ok": true,
  "asset": { ... },
  "ssot": {
    "path": "docs/ssot/apps/ssot.apps.helm.yml",
    "content": "...",
    "truncated": false
  }
}
```

### 3. Implementation plan

- Add `scripts/mcp_debug/registry.py` with `_load_registry()`, `_match_asset()`, `mcp_registry_lookup(...)`, and `mcp_registry_get(...)`.
- `mcp_registry_lookup` loads `docs/ssot/ssot.registry.yml` to discover partitions, then loads each partition's `assets` list and filters in memory. This keeps the memory footprint small (each partition is now <350 lines).
- Add tool schemas to `scripts/mcp_debug/server.py` `handle_tools_list` and dispatch in `handle_tools_call`.
- Register the tools in `~/.config/devin/mcp_config.json` and `~/.config/windsurf/mcp_config.json` if required by the client.
- Update `docs/ssot/infrastructure/ssot.mcp-debug.yml` `suggested_extensions` with a completed entry for `mcp_registry_lookup`/`mcp_registry_get`.

### 4. Security and data isolation

- Only read from `REPO_DIR / "docs" / "ssot"` and `REPO_DIR / "data"` (for runtime baselines). Refuse paths outside the repo.
- Do not write to the registry; `mcp_ssot_append` is for append-only SSOT edits and must not be used to mutate registry partitions.
- Keep `mcp_get_file` for arbitrary file fetches; registry tools are for structured lookup only.

### 5. Migration / compatibility

- Existing `mcp_read_ssot`, `mcp_search_ssot`, `mcp_query_ssot` remain unchanged.
- `mcp_query_ssot` can still be used if the caller already knows the partition path; the new tools cover the common "I know the name but not the file" case.

### 6. Open questions

1. Should `mcp_registry_lookup` also search MDDB for semantic matches, or only the local registry partitions?
2. Should we cache partition loads in memory for repeated calls in one session?
3. Should `mcp_registry_get` auto-detect `type` from the asset's `path` for callers who only know the `id`?

## Recommendation

Proceed with `mcp_registry_lookup` and `mcp_registry_get` as scoped above. The change is additive, reuses the existing partition structure, and fills the only remaining gap between the split registry and `mcp-debug` consumers.
