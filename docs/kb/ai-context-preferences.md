---
title: Personal Preferences
description: Communication style, code conventions, and tool preferences for AI agents and personal workflow
tags: [preferences, communication, code-style, tools]
created: 2026-08-11
updated: 2026-08-11
category: meta
status: active
---

# Personal Preferences

## Communication

- Be concise and direct
- Use markdown for explanations
- Prefer minimal code changes; avoid over-engineering
- Focus on practical solutions over theoretical discussions

## Code Style

- Follow existing conventions in the current codebase
- Do not add comments or docstrings unless asked
- Keep functions small and focused
- Prioritize readability over cleverness
- Use descriptive variable and function names

## Tools

### Development Environment
- **Windsurf/Cascade**: IDE-based AI coding for daily development
- **Devin**: Autonomous tasks and pull requests
- **mcp-kbman**: Knowledge base management and search
- **GitHub**: Infrastructure and project code sync

### Knowledge Management
- **Personal KB**: `/home/tony/GoogleDrive/Tony AI/KB/` (GDrive sync)
- **SSOT**: `/home/tony/CascadeProjects/chaba/docs/ssot/` (GitHub sync)
- **Project Docs**: `/home/tony/CascadeProjects/chaba/docs/` (GitHub sync)

### AI Agent Access
- AI agents access Personal KB via mcp-kbman MCP server
- Use mcp-kbman search for unified knowledge discovery
- Reference Personal KB ai-context/ for personal context and preferences

## Workflow Preferences

### Before Starting Work
- Run `bash ./kb-start.sh` for Personal KB work
- Check git status for SSOT and project docs
- Resolve any conflicts or issues before proceeding

### During Work
- Make minimal, focused changes
- Test changes before committing
- Update relevant documentation
- Follow existing patterns and conventions

### After Work
- Run `bash ./kb-end.sh "summary"` for Personal KB
- Commit SSOT and project docs with descriptive messages
- Push to GitHub for multi-machine sync
- Wait for GDrive sync before switching machines

## Communication Style with AI Agents

- Provide clear, specific requirements
- Give context about the codebase and project
- Specify success criteria upfront
- Be available for clarification if needed
- Review changes and provide feedback