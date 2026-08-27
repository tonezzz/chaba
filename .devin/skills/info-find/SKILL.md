---
name: info-find
description: Improved information-finding flow with intent routing, MDDB preflight, SSOT/code search, result merging, and per-session audit.
allowed-tools:
  - exec
  - grep
  - read
  - mcp_call_tool
  - mcp_list_tools
  - find_file_by_name
  - ask_user_question
triggers:
  - user
  - model
---

Unified information-finding flow for `chaba`.

1. Capture the query
   - Prefer an argument or the user's message. If missing, prompt for it.

2. Determine the session ID
   - Use `DEVIN_SESSION_ID` from the environment. If absent, use the process PID or ask.
   - This isolates cache and audit from every other Devin session.

3. Run the planner
   - `node .devin/skills/info-find/info-find.mjs --query "<query>" --session <id>`
   - The planner returns a JSON plan with `intent`, `use_mddb`, `use_ssot`, `use_grep`, `use_health`, `use_mcp`, `cache_dir`, `audit_path`.

4. Optional quick mode
   - If the user explicitly asks for a local/SSOT-only search, pass `--quick` to skip MDDB.

5. MDDB health preflight (only if `use_mddb` is true)
   - `exec curl -s http://127.0.0.1:11023/health`
   - If the health check does not return 200, use `ask_user_question` to offer:
     a) Fall back to SSOT/code grep
     b) Cancel the search
   - Treat 429/503 as degraded and suggest the fallback.

6. Semantic documentation search (only if MDDB is healthy)
   - `mcp_list_tools` for server `docs` to confirm the available tools.
   - `mcp_call_tool` with server `docs`, tool `search_docs`, query, and `limit` from `max_results`.
   - Display the top results with path, excerpt, and relevance.

7. SSOT YAML search (only if `use_ssot` is true)
   - `grep` across `docs/ssot/**/*.yml`, excluding `template.yml`.
   - Show 2 lines of context around each match, group by file, and count matches per file.

8. Code search (only if `use_grep` is true)
   - Use `find_file_by_name` to locate files whose extensions match the query context.
   - `grep` the most likely files with 2 lines of context.

9. Health/infrastructure search (only if `use_health` is true)
   - `grep` across `docs/ssot/infrastructure/ssot.health*.yml`.
   - `read` the matching file and the relevant `ssot.services.yml` or `ssot.health.*` section.

10. MCP tool lookup (only if `use_mcp` is true)
    - Ask the user which MCP server (e.g. `docs`, `mcp-health`, `github`).
    - `mcp_list_tools` that server, then `mcp_call_tool` as requested.
    - Before any MCP call, read the relevant policy section in `docs/ssot/infrastructure/ssot.mcp-tools.yml`.

11. Merge and rank results
    - Deduplicate by source path.
    - Rank: MDDB docs first (by relevance), SSOT matches second, code matches third.
    - Summarize counts and offer to `read` the top matches.

12. Fallback on no matches
    - `ask_user_question` with options: rephrase the query, broaden the search, or switch to a code-only search.

13. Audit
    - After the final answer, append the outcome to the session audit log:
      `node .devin/skills/info-find/info-find.mjs --session <id> --record-result '<short JSON summary>'`

Safety for other sessions:
- All cache and audit files live under `.devin/skills/info-find/cache/sessions/<session_id>/` inside the repo.
- No writes to `~/.config/devin` or global skill directories, so parallel Devin sessions on other projects are unaffected.
- Session directories are created on demand and are gitignored (`cache/`).
