---
title: MCP-Debug Raw Command Allowlist Conventions
description: How to evaluate, categorize, and gate raw commands in ssot.mcp-debug.yml
tags: [mcp-debug, commands, allowlist, security, baseline, token-optimization]
created: 2026-08-19
updated: 2026-08-19
category: operations
status: active
related:
  - docs/ssot/infrastructure/ssot.mcp-debug.yml
  - docs/kb/mcp-tools.md
  - docs/kb/mcp-server-audit.md
---

# MCP-Debug Raw Command Allowlist Conventions

## What it is

This entry documents the conventions for maintaining the raw-command allowlist in `docs/ssot/infrastructure/ssot.mcp-debug.yml`. The allowlist controls which shell commands the `mcp-debug` server may run on remote hosts.

## Context/Background

The allowlist started with a small set of vetted diagnostic commands. As the tool grew, more commands were added for git, networking, storage, hardware, and system inspection. Without structure, the list becomes hard to review, risks token bloat, and may expose privileged or interactive commands.

## Key Details

### 1. Categorize by purpose

Group the `raw` list by function so reviewers know why a command is present:

- `system-info` — `whoami`, `id`, `uname`, `hostname`, `lsb_release`
- `hardware` — `lspci`, `lscpu`, `lsmem` (avoid heavy scans)
- `storage` — `df -h`, `du` (with path limits), `lsblk`
- `network` — `ip`, `ss`, `lsof -nP`, `dig`, `resolvectl`, `ping` (with timeout)
- `process` — `ps`, `lsof -nP`, `systemctl`
- `git` — read-only subcommands only
- `json/yaml` — `jq`, `yq` for filtering output

### 2. Gate git tightly

Only allow read-only, non-destructive forms:

- `git status`
- `git log ...`
- `git diff ...`
- `git branch`
- `git remote -v`

Do not allow `git checkout`, `git reset`, `git push`, `git pull`, `git clean`, `git rebase`, or any write without explicit user approval.

### 3. Add per-command metadata

If the SSOT schema allows, annotate each command:

- `read_only: true` — command never modifies state
- `timeout` — seconds before abort
- `max_output` — soft character limit to avoid token bloat
- `hosts` — `linux`, `macos`, or `both`
- `requires_privilege` — flag commands that may need `root`

### 4. Avoid risky or open-ended commands

Remove or heavily gate:

- `python`, `node`, `npm`, `npx` — arbitrary code execution
- `dmesg` — may require root and is large
- `ping`, `traceroute`, `mtr` — can hang; require timeout and non-privileged flags
- `du` without path limits — expensive on large trees
- `find` with broad roots — slow and high-output

### 5. Baseline before whitelisting

Before adding a new command, run `mcp_stats` on both `tony_omen` and `tony_dell` and confirm `savings_pct_chars` is positive on both hosts. Only add commands that are more compact than raw shell output.

### 6. Validate after edits

Run `ssot-validate` after modifying `ssot.mcp-debug.yml` to catch YAML syntax errors, duplicate list items, or invalid command names.

## Usage/Commands

Adding a new raw command:

```bash
# 1. Propose the command and category
# 2. Run baseline on both hosts
mcp_stats(host="tony_omen", command="your-proposed-command")
mcp_stats(host="tony_dell", command="your-proposed-command")

# 3. Validate the SSOT file
ssot-validate docs/ssot/infrastructure/ssot.mcp-debug.yml

# 4. Commit with a descriptive message
git commit -m "docs: add <command> to mcp-debug allowlist"
```

## Troubleshooting

- **Command works on one host but not the other** — add a `hosts` filter or an abstract wrapper like `podman ... || docker ...`.
- **Token output is too large** — add `max_output`, use compacting, or remove low-value flags.
- **`ssot-validate` fails** — check for duplicate entries, trailing whitespace, or inconsistent 2-space indentation.

## Related Documentation

- `docs/ssot/infrastructure/ssot.mcp-debug.yml`
- `docs/kb/mcp-tools.md`
- `docs/kb/mcp-server-audit.md`
