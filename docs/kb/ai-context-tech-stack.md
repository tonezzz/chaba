---
title: Tech Stack
description: Technology stack, tools, and systems used across development environment and infrastructure
tags: [tech-stack, tools, infrastructure, development]
created: 2026-08-11
updated: 2026-08-13
category: operations
status: active
---

# Tech Stack

## Development Environment

### Editors & IDEs
- **Windsurf/Cascade**: Primary IDE for AI-assisted development
- **VS Code**: Alternative editor for specific tasks
- **Devin CLI**: Autonomous task execution and pull requests

### AI Agents
- **Devin**: Autonomous tasks, pull requests, complex workflows
- **Cascade**: IDE-based AI coding assistant
- **Claude Code**: Alternative AI coding assistant
- **Codex**: Code generation and completion

### Knowledge Management
- **Project KB**: `/home/tony/CascadeProjects/chaba-kbman/docs/kb/` (GitHub sync)
- **SSOT**: `/home/tony/CascadeProjects/chaba-kbman/docs/ssot/` (GitHub sync)
- **MDDB**: Local semantic search database with Google Drive backup
- **MCP Servers**: docs-mcp, mddb, github, workflows, postgres, weaviate

### Operating Systems
- **Primary**: Linux (Ubuntu on tony-omen)
- **Secondary**: macOS, Windows access available
- **Container**: Docker/Podman for containerized services

## Infrastructure

### MCP Servers
- **mddb**: Semantic search across documentation collections
- **docs**: Documentation search (@devista/docs-mcp)
- **github**: GitHub integration (issues, PRs, repositories)
- **workflows**: YAML workflow orchestration
- **postgres**: PostgreSQL database access
- **weaviate**: Vector database for semantic search
- **mcp-gpu**: GPU monitoring and queue management
- **yomi**: LINE conversation viewer and analysis
- **mcp-health**: System health monitoring

### Storage & Sync
- **GitHub**: Project KB, SSOT configurations, and code
- **Google Drive**: MDDB backups (Tony AI/mddb)
- **PostgreSQL**: Structured data storage
- **MDDB**: Semantic search database with native backup

### Container Management
- **lazydocker**: Container/Compose TUI
- **Docker**: Container runtime
- **Podman**: Alternative container runtime

## Development Tools

### Version Control
- **Git**: Primary version control system
- **GitHub**: Code hosting and collaboration
- **GitLab**: Alternative code hosting

### Automation
- **workflows-mcp**: YAML workflow orchestration
- **mcp-kbman**: KB workflow automation
- **Shell scripts**: Custom automation scripts

### Monitoring
- **Health checks**: System and service monitoring
- **Logs**: System and application logging
- **Metrics**: Performance and usage metrics

## System Architecture

### Knowledge Base Architecture
- **Project KB**: GitHub-synced project knowledge base
- **SSOT**: GitHub-synced infrastructure configurations
- **MDDB**: Local semantic search with Google Drive backup
- **Single Source of Truth**: Each system has clear purpose

### MCP Integration
- **Semantic search**: MDDB provides AI-powered semantic search
- **SSOT search**: ssot-search skill for YAML pattern matching
- **Workflow automation**: Auto-kb skill for session learnings
- **AI agent access**: All knowledge accessible via MCP servers

### Multi-Machine Access
- **Project KB**: GitHub sync across machines
- **SSOT**: GitHub sync across machines
- **MDDB**: Local instance with Google Drive backup sync
- **Consistent paths**: Same paths on all machines for reliability