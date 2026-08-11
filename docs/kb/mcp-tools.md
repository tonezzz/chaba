# MCP Tools Inventory
## What it is

This document tracks the MCP servers used by the chaba lab and how to maintain them.


This document tracks the MCP servers used by the chaba lab and how to maintain them.
## Context/Background

Created 2026-08-04 as part of Chaba infrastructure documentation.


## Server Inventory

| Server | Type | Command | Purpose | Secrets / Env |
| --- | --- | --- | --- | --- |
| `yomi` | stdio | `/usr/bin/node /home/tony/.yomi/mcpb/run.mjs` | LINE conversation viewer | Basic-auth on web side |
| `github` | stdio (wrapper) | `/bin/bash /home/tony/CascadeProjects/chaba/.windsurf/run-github-mcp.sh` | GitHub MCP server | `~/.config/secrets/github-mcp.env` |
| `mcp-llama` | stdio (wrapper) | `/bin/bash /home/tony/CascadeProjects/chaba/.windsurf/run-llama-mcp.sh` | Local LLM endpoint | `LLAMA_URL` |
| `playwright` | stdio | `/usr/bin/npx -y @playwright/mcp@0.0.78` | Browser automation | None |
| `playwright` | HTTP/SSE | `http://localhost:8931/mcp` | Browser automation (long-running) | `~/.windsurf/run-playwright-mcp-http.sh` |
| `mcp-kbman` | stdio | `python3 -m mcp_kbman.server` | KB management with search and workflow | `GDRIVE_MOUNT_POINT` |

## Config Files

- **Global Windsurf config** (active): `~/.codeium/windsurf/mcp_config.json`
- **Project source of truth** (versioned): `chaba/.windsurf/mcp_config.json`
- **HTTP variant** (for long-lived browser sessions): `chaba/.windsurf/mcp_config.http.json`
- **Wrapper scripts**: `chaba/.windsurf/run-github-mcp.sh`, `chaba/.windsurf/run-llama-mcp.sh`, `chaba/.windsurf/run-playwright-mcp-http.sh`

## Initial Setup

1. Copy the project config into Windsurf:
   ```bash
   cp /home/tony/CascadeProjects/chaba/.windsurf/mcp_config.json ~/.codeium/windsurf/mcp_config.json
   ```
2. Ensure `~/.config/secrets/github-mcp.env` exports `GITHUB_PERSONAL_ACCESS_TOKEN`.
3. Ensure `LLAMA_URL` is exported in the MCP config `env` or in `~/.config/secrets/llama.env`.
4. Reload Windsurf/Cascade.

## Updating Versions

- **Playwright MCP**: find the latest version with `npm view @playwright/mcp version`, then update both `mcp_config.json` and `mcp_config.http.json` (and `run-playwright-mcp-http.sh`) to use the pinned version.
- **GitHub MCP server**: update the image tag in `run-github-mcp.sh` if you ever move off `latest`.

## HTTP Transport for Playwright

For headed or long-running browser work, start the Playwright MCP server on a fixed port:

```bash
nohup /home/tony/CascadeProjects/chaba/.windsurf/run-playwright-mcp-http.sh > /tmp/playwright-mcp.log 2>&1 &
```

Then switch the Windsurf MCP config to `mcp_config.http.json` and reload the IDE. The `playwright` server will use `url` instead of spawning a new process each time.

## Troubleshooting

- `GITHUB_PERSONAL_ACCESS_TOKEN not set` — the `github` wrapper could not find the secrets file or the env var.
- `LLAMA_URL not set` — the `mcp-llama` wrapper has no target URL.
- New MCP servers not appearing — reload or restart Windsurf/Cascade after editing `mcp_config.json`.

## workflows-mcp Server

**Purpose**: YAML-based workflow orchestration and automation

**Installation**:
```bash
pipx install workflows-mcp
pipx inject workflows-mcp "mcp<2.0.0" --force  # MCP 2.0 compatibility
```

**Configuration**:
```json
{
  "mcpServers": {
    "workflows": {
      "command": "workflows-mcp",
      "env": {
        "WORKFLOWS_TEMPLATE_PATHS": "/home/tony/CascadeProjects/chaba/workflows",
        "WORKFLOWS_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

**Key Tools**:
- `list_workflows()` - List available workflows
- `execute_workflow(workflow="name", inputs={...})` - Execute registered workflow
- `execute_inline_workflow(workflow_yaml="...", inputs={...})` - Execute ad-hoc YAML
- `get_job_status(job_id="...")` - Check async job status

**MCP Compatibility**: Requires `mcp<2.0.0` due to `mcp.server.fastmcp` module removal in MCP 2.0

**Documentation**: See `docs/kb/workflows-mcp-integration.md` for detailed usage

## mcp-kbman Server

**Purpose**: Knowledge base management with multi-source search, background caching, and KB workflow compliance

**Location**: `/home/tony/CascadeProjects/chaba-kbman/mcp-kbman`

**Configuration**:
```json
{
  "mcpServers": {
    "mcp-kbman": {
      "command": "python3",
      "args": ["-m", "mcp_kbman.server"],
      "cwd": "/home/tony/CascadeProjects/chaba-kbman/mcp-kbman",
      "env": {
        "LOG_LEVEL": "INFO",
        "GDRIVE_MOUNT_POINT": "/home/tony/GoogleDrive",
        "PYTHONPATH": "/home/tony/CascadeProjects/chaba-kbman/mcp-kbman"
      }
    }
  }
}
```

**Key Tools**:
- **File Operations**: `list_gdrive_files()`, `get_gdrive_file()`, `upload_gdrive_file()`, `update_gdrive_file()`, `delete_gdrive_file()`
- **Search Operations**: `search_kb()`, `rebuild_index()`, `get_index_status()`, `clear_search_cache()`
- **Background Tasks**: `get_scheduler_status()`, `trigger_task()`, `get_task_results()`, `get_pre_generated_stats()`
- **KB Workflow**: `kb_workflow_start()`, `kb_workflow_end()`, `kb_git_status()`, `kb_git_commit()`, `kb_check_duplicates()`
- **Session Management**: `kb_read_current_context()`, `kb_update_current_context()`, `kb_read_active_projects()`, `kb_update_active_projects()`

**Features**:
- Multi-source search across Personal KB (28 docs) and Project Docs (186 docs) - 214 total documents
- Background task system with configurable intervals (60s file index, 300s search index, 3600s cleanup)
- 90%+ performance improvement through pre-generation and caching
- Full KB workflow compliance (git operations, duplicate detection, frontmatter validation)
- Search performance: ~0.1-0.3s (competitive with MCP Docs)

**Architecture**: Modular design with separate components for DocumentIndexer, SearchEngine (Whoosh), SearchCache, and SearchManager

**Documentation**: See `meta/mcp-kbman-architecture.md` for detailed architecture

## Tags

- **yomi**: yomi
- **line**: line
- **messaging**: messaging
- **conversations**: conversations
- **documentation**: documentation
- **kb**: kb
- **knowledge-base**: knowledge-base
- **workflow**: workflow
- **automation**: automation
- **mcp**: mcp
- **2026**: 2026
- **mcp-kbman**: mcp-kbman
- **search**: search
- **caching**: caching
