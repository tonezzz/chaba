---
category: operations
---

# AI Agent Tool Selection Improvements

### Current Issues
- Tools from multiple docs MCP servers without context
- No automatic project awareness
- Manual tool selection required
- Risk of using wrong project's documentation

### Proposed Improvements

#### 1. Project Context Metadata
```python
# Add project context to tool descriptions
tools = [
    {
        "name": "search_docs_chaba",
        "description": "Search chaba project documentation",
        "project": "chaba",
        "scope": "chaba knowledge base"
    },
    {
        "name": "search_docs_trade",
        "description": "Search trade project documentation", 
        "project": "trade",
        "scope": "trade knowledge base"
    }
]
```

#### 2. Context-Aware Tool Selection
```python
def select_tools_for_context(context):
    """Select appropriate tools based on project context"""
    if context.get('project') == 'chaba':
        return ['mddb', 'docs-chaba']
    elif context.get('project') == 'trade':
        return ['docs-trade', 'postgres']
    else:
        return ['mddb', 'docs-chaba', 'docs-trade']
```

#### 3. Unified Search Interface
```python
def unified_search(query, project=None):
    """Search across all projects with optional project filter"""
    if project:
        return search_project(query, project)
    else:
        results = []
        for proj in ['chaba', 'trade']:
            results.extend(search_project(query, proj))
        return deduplicate_results(results)
```

