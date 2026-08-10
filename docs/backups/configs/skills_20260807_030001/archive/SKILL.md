---
name: archive
description: Global session archiving with timestamp-based filenames
allowed-tools:
  - exec
triggers:
  - user
---

# Global Archive Session

Project-agnostic session archiving with timestamp-based filenames. Works from any project directory.

## Usage

**Non-interactive mode:**
```
node skill.mjs <project> <title> [summary]
```

**Interactive mode:**
```
node skill.mjs
```

**With project root override:**
```
node skill.mjs /path/to/project <project> <title> [summary]
```

## What It Does

1. Auto-detects project structure (chaba, generic, or fallback)
2. Creates sessions directory if needed (docs/overview/sessions/ or .sessions/)
3. Uses timestamp-based filenames to prevent overwrites (2026-08-02T09-14-41.yml)
4. Stores sessions in project-specific subdirectories
5. Records project metadata (root, type, timestamp)

## Project Detection

Automatically detects project type:
- **chaba**: Uses `docs/overview/sessions/`
- **generic**: Uses `.sessions/`
- **fallback**: Creates `docs/overview/sessions/`

## Session File Format

Creates timestamped YAML files:
```yaml
title: Session Title
date: 2026-08-02
timestamp: 2026-08-02T09:14:41.298Z
summary: 'Session summary'
project: project-name
project_root: /path/to/project
project_type: chaba
sections:
  - title: Details
    icon: �
    layout: list
    items:
      - label: Summary
        text: 'Session summary'
      - label: Project
        text: 'project-name'
      - label: Date
        text: '2026-08-02'
      - label: Project Root
        text: '/path/to/project'
```

## Benefits

- **Project-agnostic**: Works from any directory
- **No overwrites**: Timestamp-based unique filenames
- **Auto-detection**: Automatically finds/creates sessions directory
- **Flexible**: Interactive or command-line usage
- **Global**: Available across all projects via ~/.config/devin/skills/
