---
description: Pre-flight mcp_debug hosts with mcp_health before calling mcp-health
---

# MCP Health Pre-flight

Use this skill when the user asks for health checks, status, or troubleshooting on `tony_dell`, multiple hosts, or service groups that may involve `tony_dell`.

## When to use

- Before `mcp-health` `check_group`, `batch_check`, `quick_health`, or `get_troubleshooting_info` that includes `tony_dell`.
- Before asking `mcp-health` to restart or analyze a service on `tony_dell`.
- Before running any `mcp_debug` / `mcp_raw` / `mcp_logs` / `mcp_net` / `mcp_gpu` on `tony_dell`.

## Steps

1. Call `mcp_health` for the target host(s).
   - Single host: `mcp_health(host="tony_dell")`
   - Both hosts: run `mcp_health` for `tony_omen` and `tony_dell` in parallel.
2. Inspect the `ok` field.
3. If `ok` is `false`, stop. Report the `error` or `err` output and do not proceed with `mcp-health` or remote `mcp_debug`.
4. If `ok` is `true`, proceed with the intended `mcp-health` or `mcp_debug` call.

## Examples

### Check a group on both hosts

User: "check the web stack on both hosts"

1. `mcp_health(host="tony_omen")`
2. `mcp_health(host="tony_dell")`
3. If both ok: `mcp-health` `check_group(group="web-stack")` (or the appropriate local check).

### Troubleshoot a remote service

User: "why is yomi-api down on tony-dell?"

1. `mcp_health(host="tony_dell")`
2. If ok: `mcp_debug(host="tony_dell", command="systemctl list-units")` and/or `mcp_logs(host="tony_dell", unit="yomi-api.service")`

## Notes

- `mcp_health` runs `ls -l` on the `mcp-debug` binary path, which also proves SSH for `tony_dell`.
- This prevents hangs from `mcp-health` or `mcp_debug` when `tony-dell` is offline or unreachable.
