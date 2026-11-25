---
name: info-find
description: >-
  Unified information-finding for any project. Routes a query across
  project-local SSOT/code, MDDB semantic docs, policy-allowlisted MCP
  discovery, service-health files, and web/GitHub precedent — returns
  ranked results with source citations. Cache and audit are isolated
  per project + session; every source fails safe when unavailable.
allowed-tools:
  - exec
  - grep
  - read
  - web_search
  - mcp_list_tools
  - mcp_call_tool
triggers:
  - user
  - model
---

# info-find — portable unified retrieval

Portable across agents: the shared planner + source adapters live at
`scripts/devnest/info_find.py` (stdlib-only Python). The skill itself
holds no project state — all cache/audit lives under
`~/.cache/devin/info-find/<project>/sessions/<session>/`, outside any
git tree. Port to another repo by copying the script + this folder;
override endpoints via `INFO_FIND_MDDB_URL`,
`INFO_FIND_MDDB_COLLECTIONS`, `INFO_FIND_CACHE`, `INFO_FIND_PROJECT`.

## Flow

1. **Capture the query** — from the argument or the user message.

2. **Plan** — `python3 scripts/devnest/info_find.py plan --query "<q>"`
   (add `--session <id>`; defaults to `$DEVIN_SESSION_ID` or pid).
   The plan JSON gives `intent` plus `use_mddb`, `use_ssot`,
   `use_grep`, `use_health`, `use_mcp`, `use_github`, `use_web`,
   `cache_dir`, `audit_path`. `--quick` keeps it local (no mddb/web/
   github); `--web` forces the web source.

   Intents: `ssot`, `code`, `service-health`, `mcp`, `web`,
   `general-doc`, `explore` (feature/option expansion — internal
   sources first, then the GitHub precedent rung, then generic web;
   write precedent findings onto the kanban card via board-api, not
   chat memory).

3. **Run local sources** —
   `python3 scripts/devnest/info_find.py run --query "<q>"` executes
   every locally-runnable source the planner routed to and prints the
   ranked, cited result JSON. Local sources: `ssot` (search
   `**/ssot/**/*.yml` minus templates), `code` (repo source files),
   `health` (`**/ssot*health*.yml` + services files), `mddb` (health
   preflight then `/v1/search` over the doc collections), `mcp`
   (`policy.<domain>` extraction from `**/ssot.mcp-tools.yml`).
   `--sources a,b,c` restricts; `--offline` marks agent-tool sources
   `unavailable` instead of `deferred`.

4. **Run agent-tool sources** — for each source marked `deferred` in
   `sources`, execute it with your own tools and merge its results:
   - `web` → your web-search tool; cache raw JSON in the session dir;
     summarize top 3–5 with URL citations. Trade/corporate events:
     capture effectiveDate/recordDate, swapRatio/splitRatio,
     priceFactor=1/ratio, volumeFactor=ratio, parValue, newSymbol,
     sources[].
   - `github` → repo discovery via web search `"<terms> github"`, then
     implementation-level via github MCP `search_code`/`search_issues`;
     per project record name/what/why/fit/maturity.
   - `mcp` call → read the cited `policy.<domain>` section first
     (`mcp-policy <domain>` prints it), then `mcp_list_tools` +
     `mcp_call_tool` on that server only — the policy domain is the
     allowlist boundary.
   - `mddb` semantic search may ALSO be served by an MCP docs server
     when the direct HTTP bank is unreachable — an equivalent source,
     record which path produced the result.
   If you lack the tool a deferred source needs, report it
   `unavailable` — never fake results.

5. **Fail safe** — a source that is down, denied, or errors is reported
   in `sources` with `status: unavailable|error` and a `reason`;
   remaining sources still answer. Never block the whole query on one
   source; never silently swap to a different service — state the
   fallback you used. If MDDB is degraded (429/503) prefer SSOT/code
   and say so.

6. **Answer with citations** — results are pre-ranked (mddb > web >
   github precedent > ssot/health > mcp > code), deduped by citation.
   Every claim carries its citation: `{path, lines}` for repo files,
   `{collection, id, path}` for mddb, `{url}` for web. If nothing
   matches, say so and offer: rephrase, broaden, or `--web`.
   When a followed pointer/citation turns out STALE (path/key no longer
   resolves to the canonical source), record the incident once:
   `python3 scripts/chaba/pointer-stale-add.py --pointer-ref <stale-ref>
   --canonical-ref <correct-ref>` — local telemetry only, feeds the
   Phase D stale-pointer metric (OPS-1368).

7. **Audit** — `python3 scripts/devnest/info_find.py record
   --session <id> --result '<short json>' --elapsed-ms <ms>
   --resolved yes|no` appends the outcome to the session's
   `audit.ndjson`. Pass your measured wall time (query -> answer) and
   the resolved verdict — these feed the session-level time-to-find and
   verified-resolution metrics in capture-metrics.py; without them the
   find is invisible to Phase D telemetry.

## Isolation contract

- `~/.cache/devin/info-find/<project>/sessions/<session>/` per
  project+session; project is the repo name (worktrees resolve to the
  main repo), session ids are sanitized — no session can read or write
  another's cache.
- Nothing is written into the skill folder or the repo — the package
  stays read-only and reusable.
- The read-only OpenCode lane profile
  `evals/opencode-lane/profiles/info-find/` permits ONLY this script in
  bash plus the read-only MCP allowlist; its held-out verifier
  re-checks every citation. The queued card research executor is
  Phase 2 — not built yet.
