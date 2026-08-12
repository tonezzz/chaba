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

## mcp-health Server

**Purpose**: Centralized health monitoring and telemetry orchestrator for Chaba infrastructure

**Location**: `/home/tony/CascadeProjects/chaba/mcp/mcp-health/`

**Configuration**:
```json
{
  "mcpServers": {
    "mcp-health": {
      "command": "/usr/bin/node",
      "args": ["/home/tony/CascadeProjects/chaba/mcp/mcp-health/server.js"],
      "env": {
        "HEALTH_CONFIG": "/home/tony/CascadeProjects/chaba/docs/ssot/infrastructure/ssot.health.yml",
        "HEALTH_SKILL": "/home/tony/CascadeProjects/chaba/.agents/skills/health-check/SKILL.md"
      }
    }
  }
}
```

**Key Tools**:
- `check_health(service?)` - Run health checks for all or specific services
- `get_health_status()` - Get current health status from database
- `get_health_history(service_name?, limit?)` - Get historical health data
- `get_health_summary(service_name?)` - Get uptime statistics and trends

**Features**:
- Hybrid orchestrator model (MCP as coordinator, not executor)
- Network profile auto-detection (home vs mobile)
- SQLite persistence for health history
- Integration with existing health-check skill
- Reads from SSOT health configuration

**Architecture**:
- MCP Layer: Standardized tools and interfaces
- Execution Layer: Calls existing health-check skill
- Persistence Layer: SQLite database (health-history.db)
- Configuration Layer: SSOT health configuration files

**Database Schema**:
```sql
CREATE TABLE health_checks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  service_name TEXT NOT NULL,
  status TEXT NOT NULL,
  response_time REAL,
  error TEXT,
  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**Network Profile Detection**:
- Home Profile: If `tony-omen.local` resolves, uses home network config
- Mobile Profile: If home unavailable, detects current IP via `ip route get 1.1.1.1`
- URL Substitution: Automatically replaces `{profile}` placeholders with detected base URL

**Development Status**:
- Phase 1 (MVP): ✅ Complete - Basic health check orchestration
- Phase 2: ✅ Complete - SQLite persistence for health history and trends
- Phase 1+2 (Real Health Checks): ✅ Complete - HTTP, container, systemd checks with categorization
- Phase 3: ⏳ Pending - Alerting and notification capabilities

**Completed Features (Phase 1+2)**:
- Real HTTP health checks using curl with expected_status validation from SSOT config
- Container health checks using docker ps with expected_state validation from SSOT config
- Systemd health checks using systemctl with expected_state validation from SSOT config
- 4-level status categorization (healthy, degraded, error, unknown)
- Profile filtering for home/mobile networks
- Category grouping in health reports (web, api, datastore, gpu, queue, optional, system)
- Recovery action suggestions from SSOT config
- Dependency analysis and cascading failure detection
- Enhanced database schema with detailed health metrics including expected values

**Critical Gap Fixed**: Implemented expected_status and expected_state validation from SSOT configuration. Previously hardcoded expectations (200 for HTTP, "running" for containers, "active" for systemd) now use config-specified values for accurate health determination across 15 HTTP services and 11 container/systemd services.

**Documentation**: See `mcp/mcp-health/README.md` for detailed usage and troubleshooting

**YAML Syntax Note**: URL placeholders in SSOT health config must be quoted to avoid parsing errors:
```yaml
# Correct
url: "{profile}/api/health"

# Incorrect (causes "Unexpected scalar" error)
url: {profile}/api/health
```

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
