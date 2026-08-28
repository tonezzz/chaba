---
category: operations
---

# KB Workflow Integration with mcp-kbman

**Integration Date**: 2026-08-11

**Purpose**: mcp-kbman provides KB workflow compliance that can be integrated with workflows-mcp for automated KB management tasks.

**KB Documentation**: See Personal KB `meta/kb-workflow-integration.md` for complete KB workflow details

### KB Workflow Tools in mcp-kbman

- **Workflow Start**: `kb_workflow_start()` - Complete workflow check before work
- **Workflow End**: `kb_workflow_end(summary)` - Commit changes and update changelog
- **Git Operations**: `kb_git_status()`, `kb_git_diff()`, `kb_git_commit()`
- **Duplicate Detection**: `kb_check_duplicates()` - Detect GDrive naming conflicts
- **Frontmatter Validation**: `kb_validate_frontmatter()` - Ensure proper KB entry format
- **Session Management**: `kb_read_current_context()`, `kb_update_current_context()`, `kb_read_active_projects()`, `kb_update_active_projects()`

### Example Workflow Integration

Create a KB management workflow in YAML:

```yaml
name: kb-daily-sync
description: Daily KB sync and validation
inputs:
  summary:
    type: str
    description: "Commit summary for the sync"

blocks:
  - id: kb-start
    type: Shell
    command: "cd /home/tony/CascadeProjects/chaba-kbman/mcp-kbman && python3 -c 'from workflow.coordinator import WorkflowCoordinator; coordinator = WorkflowCoordinator(); check = coordinator.kb_start_check(); print(check[\"ready_for_work\"])'"
  
  - id: kb-end
    type: Shell
    command: "cd /home/tony/CascadeProjects/chaba-kbman/mcp-kbman && python3 -c 'from workflow.coordinator import WorkflowCoordinator; coordinator = WorkflowCoordinator(); result = coordinator.kb_end_commit(\"{{inputs.summary}}\"); print(result[\"success\"])'"
```

### Integration Benefits

- **Automated workflow checks**: Ensure KB is ready before automated operations
- **Structured KB management**: Use mcp-kbman tools in workflows for consistent KB operations
- **Error handling**: Leverage mcp-kbman's validation and duplicate detection in workflows
- **Session tracking**: Integrate current-context and active-projects management in workflows

