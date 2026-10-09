---
category: operations
---

# Crush multi-agent isolation

**Abstract**: charmbracelet/crush (adopted as alt-lane, lab-crush-cli) shares
`~/.config/crush/crush.json` and in-cwd `.crush/` state — concurrent agents on the
same host clobber each other. This runbook is the isolation recipe.

## The incident (lab-crush-cli, 2026-10-09)

Two agents ran the same crush lab on tony-dell concurrently. Agent B's session in
the shared `/tmp/crush-lab` overwrote agent A's `fizzbuzz.py` mid-run and rewrote
the **global** `~/.config/crush/crush.json` with its own MCP/permissions/options —
agent A's results were only trustworthy after re-running isolated.

Same incident class as the worktree rules in AGENTS.md: shared mutable state +
parallel sessions = silent corruption.

## The recipe

**Per-agent scratch cwd** — never share a crush working directory:

```bash
CRUSH_DIR=/tmp/crush-lab-$(hostname)-$(whoami)-$$  # or a stable per-task name
mkdir -p "$CRUSH_DIR"
crush run -c "$CRUSH_DIR" "<prompt>"
```

**Project-local config over global** — write `.crush.json` (or `crush.json`) in the
scratch dir; it merges over `~/.config/crush/crush.json` (more specific wins).
Keep provider creds global, but put `permissions.allowed_tools`, MCP servers, and
`options` project-local so another agent's global-config writes can't move yours:

```json
{
  "permissions": {"allowed_tools": ["view", "edit", "write", "bash", "ls", "glob", "grep"]},
  "mcp": {"lab": {"type": "stdio", "command": "python3", "args": ["./lab_mcp.py"]}}
}
```

**Never edit `~/.config/crush/crush.json` from an automated run** — treat it like
the ada-pi deploy rule: snapshot-first. If a run must touch global config, use a
temp config dir via `XDG_CONFIG_HOME` override instead.

## Gotchas carried from the lab

- `--yolo` / `-y` is advertised in `--help` but **rejected by the flag parser in
  v0.98.0** — unattended runs need `permissions.allowed_tools` in config.
- Tool names for the allowlist: `agent, bash, diagnostics, download, edit, fetch,
  glob, grep, ls, multiedit, todos, view, web_search, write`.
- Session db: `<cwd>/.crush/crush.db` (sqlite; sessions/messages/parts tables) —
  audit trail lives there, per-cwd isolation keeps it clean.
- Full lab outcome: `docs/ssot/jobs/lab/2026-10-09-crush-cli-assessment.yml`.
