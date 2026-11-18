# Dispatch outcome: ada-control MCP session-dir connect race

Card: `ada-control-mcp-session-dir-race-9d9284` · runner: tony-omen · date: 2026-11-18

## Root cause (verified)

In the anomalyco/opencode fork (`packages/core/src/mcp/client.ts`), a `type: "local"`
MCP server spawns with `cwd = McpStdio.resolveCwd(sessionDirectory, config.cwd)`.
With `config.cwd` unset, cwd is the OpenChamber session workspace
(`~/.config/openchamber/chats/<date>/session-<uuid>`). The Effect
`ChildProcess` spawner pre-flights `FileSystem.access(cwd)` before exec — so when
the ephemeral chat dir is missing at spawn time (created late, or discarded
between location resolution and spawn), the connect dies with
`NotFound: FileSystem.access (...)`. It is a **parent-side** check: `ada_mcp.py`
never starts, which is why its existing `Path.cwd()` fallback could never help.

The race is real and hot: 19 failures on idc02 today, 64 on tony-dell, and every
failed session's chat dir is absent afterwards (empty dirs get discarded).

## Fix applied (option c — pin MCP cwd)

`mcp.ada-control.cwd = "/home/tony/CascadeProjects/ada-voice"` in
`~/.config/opencode/opencode.json` on **both** pane hosts:

- **idc02** (canonical pane since the morning migration; managed opencode
  2.3.2 at `~/.local/node/bin/opencode`, `OPENCODE_CONFIG` per-instance json
  only injects plugins — `mcp` comes from the global file)
- **tony-dell** (live soak fallback; same wiring, same latent bug)

Backups: `opencode.json.bak-cwd-fix-20261118` on each host. The field is a
documented fork config option (`Mcp.LocalConfig.cwd`). Config hot-reloads —
no unit restart was needed; a reconcile fired on edit.

Side benefit: `ada_mcp.py`'s `WORKSPACE` now resolves to the ada-voice
checkout, so its `.opencode/*` feature detection and `cwd=WORKSPACE`
subprocess calls run against a real project instead of an empty/discarded
chat dir.

## Verification

Deterministic race reproduction on the managed instance (basic auth
`opencode:$OPENCODE_SERVER_PASSWORD` from the child's env):

1. `mkdir D` (fresh `session-<uuid>` chat dir)
2. `GET /api/config?location[directory]=D` → 200 (location resolved & cached)
3. `rmdir D` — the race window
4. `GET /api/mcp?location[directory]=D` → forces location init + MCP connect

**Pre-fix**: produced exactly the reported failure —
`mcp connect failed ... NotFound: FileSystem.access (D)`.

**Post-fix, 20 consecutive runs** (full session.create + init sequence,
dir deleted mid-init each time): **20 × `mcp connected tools=26` at
14:00:17–14:00:53 UTC, zero `mcp connect failed`.** Last failure on idc02 was
13:59:25 UTC — the pre-fix repro. Dell single-shot repro: `mcp connected
tools=26` at 14:02:25 UTC.

Done-criterion met: 20 consecutive session starts, zero failures.

## Trail / follow-ups

- Job file: `docs/ssot/jobs/devnest/2026-11-18-ada-control-mcp-cwd-race-fix.yml`
- Follow-up worth filing upstream: OpenChamber could materialize the chat dir
  before registering the session, and/or the fork could tolerate a missing
  MCP cwd — any other local MCP server without a pinned `cwd` keeps this race.
- If another pane host is ever provisioned, carry the `cwd` pin in its
  `ada-control` block.

## How to re-verify

`rg "mcp connect failed" ~/.local/share/opencode/log/opencode.log` on idc02 —
expect no new `NotFound: FileSystem.access` ada-control lines on new sessions.
