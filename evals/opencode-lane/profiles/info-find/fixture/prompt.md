Answer this query through the shared info-find pipeline and emit the
result JSON as your final message.

Query: {{task}}

Steps:
1. `python3 scripts/devnest/info_find.py plan --query "<query>"
   --session <job-id>` — read intent + routed sources.
2. `python3 scripts/devnest/info_find.py run --query "<query>"
   --session <job-id>` — executes all locally-runnable sources
   (ssot/code/health/mddb/mcp-policy); the output IS your base result.
3. For sources marked `deferred`: serve `mcp`-type lookups only through
   your read-only MCP allowlist (list tools first, call within the
   policy domain the run cited). `web`/`github` are not available in
   this lane — keep them `unavailable` with reason `no_tool`.
4. Keep every `sources` status entry; add a `reason` for anything not
   `ok`. Merge any deferred-source results you served into `results`,
   keeping rank order mddb > web > github > ssot/health > mcp > code.
5. `answer`: 2-4 sentences grounded in the top results; if nothing was
   found, say so plainly — do not guess.

Emit ONLY the JSON: {question, intent, answer, session, sources,
results, read_only: true, cache_dir} — echo cache_dir/session from the
run output.
