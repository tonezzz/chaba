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

Add two new registry tools, keep existing SSOT tools unchanged.

### 1. `mcp_registry_lookup` tool

**Input schema:**

```json
{
  "host": "tony_omen",
  "q": "helm",
  "type": "ssot",
  "by": "any",
  "limit": 5,
  "offset": 0
}
```

- `host`: target host (the `mcp-debug` MCP server on that host reads its local `chaba` repo). For now the lookup uses the server's `REPO_DIR`; `host` selects which server to query.
- `q`: optional keyword/id/name/path fragment. If omitted, returns assets filtered only by `type`.
- `type`: optional filter (`ssot`, `script`, `service`, `timer`, `stack`, `h3-app`, `all`).
- `by`: search fields — `any` (default), `id`, `name`, `path`, `purpose`, `tags`. Matching is case-insensitive and substring-based.
- `limit`: max results.
- `offset`: pagination offset (default 0).

**Output contract:**

```json
{
  "ok": true,
  "q": "helm",
  "by": "any",
  "type": "ssot",
  "offset": 0,
  "limit": 5,
  "total": 1,
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
      "registry_file": "docs/ssot/ssot.registry.ssot-apps.yml",
      "partition": "ssot-apps"
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
  "id": "helm",
  "ssot_limit": 20000
}
```

- `id` or `path`: one is required. `id` is searched across partitions; `path` resolves directly to the asset's `path`.
- `ssot_limit`: max characters of the source SSOT file to return (default 20000).

**Output contract (single match):**

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

**Output contract (ambiguous id):**

```json
{
  "ok": false,
  "error": "multiple assets match 'helm'",
  "candidates": [
    { ... },
    { ... }
  ]
}
```

### 3. Implementation plan

- Add `scripts/mcp_debug/registry.py` with:
  - `_load_registry()` — parse `ssot.registry.yml`, discover partitions, and load all `assets` into an in-memory index.
  - `_match_asset(asset, q, by)` — case-insensitive substring matching across selected fields.
  - `mcp_registry_lookup(...)` — return paginated, filtered asset metadata.
  - `mcp_registry_get(...)` — resolve one asset by `id`/`path` and read its source SSOT.
- `mcp_registry_lookup` loads `docs/ssot/ssot.registry.yml` to discover partitions, then loads each partition's `assets` list and filters in memory. Each partition is now <350 lines, so the total index is small.
- Add tool schemas to `scripts/mcp_debug/server.py` `handle_tools_list` and dispatch in `handle_tools_call`.
- If the Devin/Windsurf MCP client requires static tool lists, update `~/.config/devin/mcp_config.json` and `~/.config/windsurf/mcp_config.json`. The `mcp-debug` server already advertises tools dynamically, so this is likely unnecessary.
- Update `docs/ssot/infrastructure/ssot.mcp-debug.yml` `suggested_extensions` with a completed entry for `mcp_registry_lookup`/`mcp_registry_get`.

### 4. Security and data isolation

- Only read from `REPO_DIR / "docs" / "ssot"` and `REPO_DIR / "data"` (for runtime baselines). Refuse paths outside the repo.
- Do not write to the registry; `mcp_ssot_append` is for append-only SSOT edits and must not be used to mutate registry partitions.
- Keep `mcp_get_file` for arbitrary file fetches; registry tools are for structured lookup only.

### 5. Migration / compatibility

- Existing `mcp_read_ssot`, `mcp_search_ssot`, `mcp_query_ssot` remain unchanged.
- `mcp_query_ssot` can still be used if the caller already knows the partition path; the new tools cover the common "I know the name but not the file" case.

### 6. Future extensions

- `mcp_registry_list(type, limit, offset)` could be a thin alias over `mcp_registry_lookup` with `q` omitted. For v1, the optional `q` handles this case.
- Add `mcp_registry_refresh()` to clear an in-memory partition cache (if caching is added later).
- Add `mcp_registry_related(id)` to follow `related`/`related_files` links and return a small graph.

### 7. Open questions

1. Should `mcp_registry_lookup` also search MDDB for semantic matches, or only the local registry partitions? (Proposed: local partitions for v1; MDDB fallback can be added later.)
2. Should we cache partition loads in memory for repeated calls in one session? (Proposed: no cache for v1; read is cheap and stateless.)
3. Should `mcp_registry_get` auto-detect `type` from the asset's `path` for callers who only know the `id`? (Proposed: yes — it searches all partitions and disambiguates by `id`/`path`.)

## Recommendation

Proceed with `mcp_registry_lookup` and `mcp_registry_get` as scoped above. The change is additive, reuses the existing partition structure, and fills the only remaining gap between the split registry and `mcp-debug` consumers.
