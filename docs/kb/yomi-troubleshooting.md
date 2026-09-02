---
category: operations
---

# Troubleshooting

- `mcp0_list_conversations` / script fails with "No persisted LINE session" → the Yomi MCP server is not pointing at the data dir with the LINE credentials. Check the `mcpServers` config and restart the client.
- Running a second Yomi server on the same `~/.local/share/yomi` while another holds `search-index.db` will block.
- If messages look garbled after a Yomi update, inspect the raw `get_chat_messages` output and adjust the CSV tokenizer in `fetch-conversations.mjs`.
- Process status stuck in "processing" → Check `process-status.json` and clear if needed: `rm /home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/process-status.json`
- Summaries not generating → Check Llama API is accessible at `http://localhost:8001/v1/chat/completions` and GPU is available
- **GPU memory exhaustion** → Phi-3 using 2944MB/4096MB (72%). Thai legal model (5GB) cannot load. Context size exceeded errors indicate model overload. Consider rate limiting or GPU upgrade (2026-08-06).
- Daily summaries empty → Ensure `process-conversations.mjs` includes `generateDailySummaries()` call (added in 2026-08-03 fix). Previously only available in legacy `update-conversations.mjs`.
- Summary language mismatch → Language-aware summarization implemented (2026-08-03) with Thai/English/mixed detection. Some encoding issues remain for certain conversations.
- Frequent Llama API 500 errors → Rate limiting and circuit breakers implemented (2026-08-03) to manage GPU load. Check `/api/yomi/rate-limiter-status` for current state.
- **Yomi API not responding** → Check `yomi-api.service` status: `systemctl status yomi-api.service`. Service auto-restarts on failure (added 2026-08-04).
- **LINE API rate limit (code 103)** → Authentication temporarily restricted. Wait 1-24 hours for restriction to lift, then re-login with `npx @rikaidev/yomi login`. Implement exponential backoff for login retries to prevent future rate limits. (2026-08-06)
- **Intermittent PC usage** → Yomi timers configured with skip logic and boot services to handle PC being off for extended periods. Fetch skips if last successful fetch within 30 minutes, processing skips if last successful processing within 12 hours. Boot services run forced operations on startup if needed. (2026-08-11)
- **`yomi/login` or `npx @rikaidev/yomi login` fails with "PIN verification failed or timed out"** → The passwordless long-poll timeout in `~/.yomi/mcpb/dist/line/auth/pwless/index.js` is too short: LINE closes the poll before the PIN can be entered and approved. Patch `x-lst` to `'180000'` ms and `DEFAULT_CONFIG.pollTimeout` to `185000` ms, or use the `mcp-yomi.sh` wrapper in `chaba-tony-dell/scripts/mcp-scripts/` which applies the patch on each launch and is referenced from `ssot.mcp.yml`. (2026-09-02)

