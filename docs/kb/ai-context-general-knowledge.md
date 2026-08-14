---
title: General Knowledge
description: General information about Tony, timezone, workflows, and knowledge base architecture
tags: [general, personal, workflow, architecture]
created: 2026-08-11
updated: 2026-08-13
category: meta
status: active
---

# General Knowledge

- Name: Tony
- Time zone: UTC+7
- Primary goal: Build a syncable knowledge base that works with Devin, Windsurf, and other AI tools.

## Knowledge Base Architecture

**Project KB** (Primary): `/home/tony/CascadeProjects/chaba-kbman/docs/kb/`
- Sync: GitHub (chaba-kbman repository)
- Purpose: Project knowledge base with MDDB integration
- Access: MDDB semantic search, MCP docs server
- Workflow: Git workflow with auto-kb skill for session learnings

**SSOT Configurations** (Infrastructure): `/home/tony/CascadeProjects/chaba-kbman/docs/ssot/`
- Sync: GitHub (chaba-kbman repository)
- Purpose: Infrastructure configurations and service definitions
- Access: GitHub web interface and git operations
- Workflow: Standard git workflow

**MDDB Knowledge Base** (Semantic Search): Local MDDB instance
- Sync: Native backup API + Google Drive sync (Tony AI/mddb)
- Purpose: AI-powered semantic search across all documentation
- Access: MDDB Panel (http://tony-omen.local:3002), MCP tools
- Collections: chaba-*, trade-*, infrastructure-ssot, communications-*

## Common Workflows

### Project KB Workflow
- Use standard git workflow for docs/kb/ and docs/ssot/
- Commit changes with descriptive messages
- Use auto-kb skill to capture session learnings
- Push to GitHub for multi-machine sync
- Use MDDB semantic search for documentation discovery

### SSOT Workflow
- Use standard git workflow for infrastructure configurations
- Validate SSOT files with ssot-validate skill
- Use ssot-search skill for SSOT-specific searches
- Commit changes with proper formatting

### AI Agent Access
- AI agents access Project KB via MDDB semantic search
- AI agents access SSOT via ssot-search skill
- Use MDDB MCP tools for semantic search across collections
- Reference ai-context-* files for personal context (general-knowledge, preferences, tech-stack)

## System Locations

- **Project KB**: `/home/tony/CascadeProjects/chaba-kbman/docs/kb/`
- **SSOT**: `/home/tony/CascadeProjects/chaba-kbman/docs/ssot/`
- **MDDB**: Local instance at http://tony-omen.local:3002
- **MDDB Data**: `/home/tony/CascadeProjects/chaba-kbman/stacks/web/mddb/`
- **MDDB Backup**: Google Drive (Tony AI/mddb)