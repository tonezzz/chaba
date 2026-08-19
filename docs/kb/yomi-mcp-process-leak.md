---
category: troubleshooting
---

# Yomi MCP Process Leak

## What it is

Each Devin/Windsurf session spawns multiple Yomi MCP server processes (`~/.yomi/mcpb/run.mjs`). When the session ends, these processes are NOT killed — they become orphaned (reparented to PID 1/systemd) and continue running, consuming RAM and CPU indefinitely.
## Context/Background

Created 2026-08-05 as part of Chaba infrastructure documentation.


## Impact

- **Per session**: ~16 Yomi processes × ~170MB = ~2.7GB per session
- **Accumulation**: After several sessions, 14+ orphans accumulated → ~8GB of wasted RAM + 10GB of swap pressure
- **Swap exhaustion**: System reached 46GB/47GB swap used, causing heavy I/O and load average 13+

## Root Cause

The Yomi MCP server (`run.mjs`) is launched by the IDE as a subprocess for each MCP connection. On IDE exit, the subprocess management doesn't SIGTERM the Yomi processes, so they linger as daemons.

## Fix Applied (2026-08-05)

Manually killed 14 orphaned instances (PIDs 1550563–1881206, started 14:32–18:24):
```bash
kill 1550563 1624473 1625313 1626012 1680464 1801239 1802052 1804111 1858617 1859048 1860685 1879669 1880132 1881206
```
Result: freed ~2GB RAM, ~10GB swap.

## Detection

```bash
# Check for orphaned Yomi instances (parent = systemd/PID 1)
ps aux | grep "yomi/mcpb/run.mjs" | grep -v grep | wc -l

# Show instances with start time and memory
ps aux | grep "yomi/mcpb/run.mjs" | grep -v grep | \
  awk '{print $2, $9, int($6/1024)"MB"}' | sort -k2
```

## Mitigation: Session-Start Cleanup

Add to `~/.bashrc` or run before starting Devin:
```bash
# Kill orphaned Yomi MCP instances (parent = PID 1) before starting new session
pkill -f "yomi/mcpb/run.mjs" 2>/dev/null || true
```

Or, a more targeted approach that only kills orphans:
```bash
ps aux | grep "yomi/mcpb/run.mjs" | grep -v grep | while read user pid rest; do
  ppid=$(ps -o ppid= -p $pid 2>/dev/null | tr -d ' ')
  [ "$ppid" = "1" ] && kill $pid 2>/dev/null
done
```

## Long-term Fix

Configure the Yomi MCP server as a singleton systemd user service:
```bash
# /home/tony/.config/systemd/user/yomi-mcp.service
[Service]
ExecStart=/usr/bin/node /home/tony/.yomi/mcpb/run.mjs
Restart=on-failure
```
This ensures only one instance runs and it restarts cleanly across sessions.

## Related

- `ssot.devin.tools.yml` — MCP server configuration
- `ssot.token-optimization.yml` — MCP server overhead reduction

## Tags

- **yomi**: yomi
- **line**: line
- **messaging**: messaging
- **conversations**: conversations
- **documentation**: documentation
- **kb**: kb
- **knowledge-base**: knowledge-base
- **ssot**: ssot
- **configuration**: configuration
- **infrastructure**: infrastructure
- **2026**: 2026
