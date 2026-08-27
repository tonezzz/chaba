---
name: info-find
description: Unified information-finding flow for any project. Supports MDDB docs, SSOT/code search, health lookup, MCP tools, and Google/web search for external events.
allowed-tools:
  - exec
  - grep
  - read
  - mcp_call_tool
  - mcp_list_tools
  - find_file_by_name
  - ask_user_question
  - web_search
  - webfetch
triggers:
  - user
  - model
---

Unified information-finding flow for `chaba`, `trade`, and any other project in the workspace.

1. Capture the query
   - Prefer an argument or the user message. If missing, prompt for it.

2. Determine the session and project
   - Session: use `DEVIN_SESSION_ID` from the environment. If absent, use the process PID or ask.
   - Project: derived from the current working directory's basename (e.g. `chaba`, `trade`).
   - Cache and audit are stored under `~/.cache/devin/info-find/<project>/sessions/<id>/`, so other sessions and projects stay isolated.

3. Run the planner
   - `node .devin/skills/info-find/info-find.mjs --query "<query>" --session <id>`
   - The planner returns a JSON plan with `intent`, `use_mddb`, `use_ssot`, `use_grep`, `use_health`, `use_mcp`, `use_web`, `cache_dir`, `audit_path`.
   - Add `--quick` to skip MDDB/web and stay local.
   - Add `--web` to force a web search even for `general-doc` queries.

4. Intent routing
   - `ssot` → `**/ssot/**/*.yml` (matches both `docs/ssot/` and `config/ssot/`)
   - `code` → repo source files
   - `service-health` → `**/ssot*health*.yml`
   - `mcp` → MCP tool lookup
   - `web` → Google/web search for external facts (stock events, corporate actions, news, docs not in MDDB)
   - `general-doc` → MDDB first, then SSOT, then optionally web if `--web` is used

5. MDDB health preflight (only if `use_mddb` is true)
   - `exec curl -s http://127.0.0.1:11023/health`
   - If the health check does not return 200, use `ask_user_question` to offer:
     a) Fall back to SSOT/code grep
     b) Fall back to web search
     c) Cancel the search
   - Treat 429/503 as degraded and suggest the fallback.

6. Semantic documentation search (only if MDDB is healthy)
   - `mcp_list_tools` for server `docs` to confirm the available tools.
   - `mcp_call_tool` with server `docs`, tool `search_docs`, query, and `limit` from `max_results`.
   - Display the top results with path, excerpt, and relevance.

7. SSOT YAML search (only if `use_ssot` is true)
   - `grep` across `**/ssot/**/*.yml`, excluding `**/*template*.yml`.
   - Show 2 lines of context around each match, group by file, and count matches per file.
   - For `chaba` this matches `docs/ssot/**`; for `trade` it matches `config/ssot/**`.

8. Code search (only if `use_grep` is true)
   - Use `find_file_by_name` to locate files whose extensions match the query context.
   - `grep` the most likely files with 2 lines of context.

9. Health/infrastructure search (only if `use_health` is true)
   - `grep` across `**/ssot*health*.yml`.
   - `read` the matching file and the relevant `ssot.services.yml` or `ssot.health.*` section.

10. MCP tool lookup (only if `use_mcp` is true)
    - Ask the user which MCP server (e.g. `docs`, `mcp-health`, `github`).
    - `mcp_list_tools` that server, then `mcp_call_tool` as requested.
    - Before any MCP call, `grep` the relevant `policy.<domain>` section in the first matching `**/ssot.mcp-tools.yml`.

11. Web search (only if `use_web` is true)
    - `web_search` with the query and `num_results` from `max_results`.
    - Cache the result JSON under `~/.cache/devin/info-find/<project>/sessions/<session>/<query-hash>-web.json`.
    - For each top result, optionally `webfetch` the page and extract key facts.
    - If the page is a PDF or JS-heavy site, prefer the snippet from `web_search` or use `browser-helper`/`playlive` if available.
    - For **trade/corporate events**, look for:
      - `effectiveDate` / `recordDate`
      - `swapRatio`, `splitRatio`, or `dividendAmount`
      - `priceFactor` = `1 / swapRatio` (or `1 / splitRatio`)
      - `volumeFactor` = `swapRatio` (for share-count changes)
      - `parValue` and `newSymbol` if the ticker changes
      - `sources` with the source URLs
    - For **general web** queries, summarize the top 3–5 results with title, URL, and a one-sentence excerpt.

12. Merge and rank results
    - Deduplicate by source path.
    - Rank: MDDB docs first (by relevance), official web results second, SSOT matches third, code matches fourth.
    - For trade, also produce an `events` JSON snippet that can be appended to a `*_history.json` file.
    - Summarize counts and offer to `read` the top matches.

13. Fallback on no matches
    - `ask_user_question` with options: rephrase the query, broaden the search, switch to web search, or switch to code-only.

14. Audit
    - After the final answer, append the outcome to the session audit log:
      `node .devin/skills/info-find/info-find.mjs --session <id> --record-result '<short JSON summary>'`

Safety for other sessions:
- All cache and audit files live under `~/.cache/devin/info-find/<project>/sessions/<session_id>/`.
- Project name is derived from the current working directory, so `chaba`, `trade`, and any other project do not share cache.
- Nothing is written to the skill directory, so the skill itself stays read-only and reusable.
- Session directories are created on demand and are outside any git tree.
