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

This entry documents the conventions for maintaining the raw-command allowlist in `docs/ssot/infrastructure/ssot.mcp-debug.yml`. The `raw` list defines which shell commands the `mcp-debug` server may execute on remote hosts. The `categories` map tags every allowed command by function.

## Context/Background

The allowlist grew from a small set of vetted diagnostic commands to cover git, networking, storage, hardware, and system inspection. To keep it maintainable, each raw command now has a category, and several risky or open-ended commands have been removed from the list.

## Key Details

### 1. Categorize every command

The SSOT now keeps a `categories` map that assigns each raw prefix to a functional category. Current categories include:

- `process` — `systemctl`, `ps`, `pgrep`, `pkill`, `nohup`, `top`
- `container` — `podman`, `docker`
- `storage` — `df`, `mount`, `lsblk`, `lsusb`, `du`
- `network` — `ss`, `lsof`, `ip`, `tailscale`, `dig`, `nslookup`, `host`, `resolvectl`, `netstat`, `ssh`, `curl`
- `system` — `journalctl`, `env`, `free`, `uptime`, `systemd-analyze`
- `system-info` — `whoami`, `id`, `uname`, `hostname`, `lsb_release`, `which`, `whereis`
- `hardware` — `lspci`, `lsmod`, `modinfo`, `lsmem`, `lscpu`
- `macos` — `launchctl`, `vm_stat`, `diskutil`, `system_profiler`, `scutil`, `sw_vers`, `sysctl`
- `text` — `tail`, `head`, `cat`, `ls`, `find`, `locate`, `grep`, `sed`, `awk`, `xargs`, `sort`, `uniq`, `cut`, `wc`, `file`, `stat`, `readlink`, `realpath`
- `json` — `jq`, `yq`
- `package` — `apt`, `apt-get`, `apt-cache`, `apt-mark`, `dpkg`
- `gpu` — `nvidia-smi`, `rocm-smi`
- `git` — `git` (must still be gated to read-only subcommands)
- `script` — `python3`

When adding a new raw command, add it to the `raw` list and to the `categories` map. Use an existing category or create a new one and document why it is needed.

### 2. Gate git tightly

`git` is in the allowlist, but only read-only, non-destructive subcommands should be used:

- `git status`
- `git log ...`
- `git diff ...`
- `git branch`
- `git remote -v`

Do not allow `git checkout`, `git reset`, `git push`, `git pull`, `git clean`, `git rebase`, or any write without explicit user approval.

### 3. Avoid risky or open-ended commands

The following are currently **not** in the allowlist because they are unsafe, slow, or too open-ended:

- `dmesg` — may require root and is large
- `ping`, `traceroute`, `mtr` — can hang; use `curl`/`dig` for network checks instead
- `python`, `node`, `npm`, `npx` — arbitrary code execution; the only script interpreter is `python3`, and it should be used with extreme caution
- `du` without path limits — expensive on large trees
- `find` with broad roots — slow and high-output

### 4. Baseline before whitelisting

Before adding a new command, run `mcp_stats` on both `tony_omen` and `tony_dell` and confirm `savings_pct_chars` is positive on both hosts. Only add commands that are more compact than raw shell output. The `mcp_savings` report now includes the `category` for each raw prefix.

### 5. Validate after edits

Run `ssot-validate` after modifying `ssot.mcp-debug.yml` to catch YAML syntax errors, duplicate list items, missing category entries, or invalid command names.

## Usage/Commands

Adding a new raw command:

```bash
# 1. Propose the command and add it to both the raw list and the categories map
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
- **`ssot-validate` fails** — check for duplicate entries, missing `categories` map entry, trailing whitespace, or inconsistent 2-space indentation.

## Related Documentation

- `docs/ssot/infrastructure/ssot.mcp-debug.yml`
- `docs/kb/mcp-tools.md`
- `docs/kb/mcp-server-audit.md`
