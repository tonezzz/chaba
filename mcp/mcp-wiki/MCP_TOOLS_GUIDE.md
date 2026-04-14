# MCP-Wiki Tools for Windsurf

## Available MCP Tools

| Tool | Purpose | Use Case |
|------|---------|----------|
| `wiki_search` | Find existing articles | Check if topic exists before writing |
| `wiki_semantic_search` | Semantic search by meaning | Find conceptually related articles |
| `wiki_hybrid_search` | Combined keyword + semantic | Best of both search methods |
| `wiki_get` | Read article content | Get full article with metadata |
| `wiki_create` | Create new article | Save documentation from editor |
| `wiki_update` | Edit existing article | Update outdated content |
| `wiki_delete` | Remove article | Cleanup obsolete docs |
| `wiki_list` | Browse recent articles | Discover existing docs |
| `wiki_validate` | Check content quality | Validate before posting |
| `wiki_explain` | Get article analysis | Understand article structure & issues |
| `wiki_enhance` | Run AI enhancement | Auto-classify, summarize, validate |
| `wiki_suggest_tags` | Get tag recommendations | Auto-tag new articles |

## Windsurf Configuration

Add to your Windsurf MCP settings:

```json
{
  "mcpServers": {
    "wiki": {
      "command": "docker",
      "args": [
        "exec", "-i", "idc1-mcp-wiki",
        "node", "index.js"
      ],
      "env": {
        "MCP_STDIO": "1",
        "WIKI_HTTP_DISABLED": "1"
      }
    }
  }
}
```

**Note:** `WIKI_HTTP_DISABLED=1` is required when using `docker exec` to prevent port conflicts with the already-running HTTP server in the container.

### HTTP SSE Configuration (Preferred)

For remote connections or when not using docker exec:

```json
{
  "mcpServers": {
    "wiki": {
      "url": "http://idc1.surf-thailand.com:3008/mcp/sse"
    }
  }
}
```

**No API key required** for SSE transport - auth is handled at the HTTP level.

## Example Workflows

### 1. Save Current File as Wiki Article
```
"Save this file as wiki article titled 'Docker Deployment Guide' with tags [docker, deployment]"
→ wiki_validate (check content first)
→ wiki_create (if valid)
```

### 2. Update Existing Documentation
```
"Update the PostgreSQL article with these new connection troubleshooting steps"
→ wiki_get (read current)
→ wiki_explain (see structure)
→ wiki_update (merge changes)
→ wiki_enhance (re-validate)
```

### 3. Validate Before Commit
```
"Check this markdown for errors before I save it"
→ wiki_validate (spelling, syntax, diagrams)
→ Shows: errors, warnings, quality score, fixes
```

### 4. Discover Related Content
```
"Find all articles about deployment"
→ wiki_search (query: "deployment")
→ Shows: matching articles with snippets
```

### 5. Semantic Search (Conceptual Matching)
```
"Find articles about container orchestration even if they don't use those exact words"
→ wiki_semantic_search (query: "container orchestration", limit: 5)
→ Finds: Docker, Kubernetes, containerization articles by meaning
```

### 6. Hybrid Search (Best Results)
```
"Search for deployment guides with both keyword and semantic matching"
→ wiki_hybrid_search (query: "deployment", limit: 10, alpha: 0.5)
→ Combines keyword matches with semantic similarity for best results
```

## Search Comparison

| Method | Best For | Speed | Accuracy |
|--------|----------|-------|----------|
| `wiki_search` | Exact keyword matching | Fast | Good for known terms |
| `wiki_semantic_search` | Conceptual queries | Medium | Finds related concepts |
| `wiki_hybrid_search` | Balanced results | Medium | Best overall quality |

**Alpha parameter (hybrid):**
- `0.0` = Keyword only
- `0.5` = Balanced (default)
- `1.0` = Semantic only

## Tool Details

### wiki_explain vs Sequential Thinking

**Sequential Thinking** is a general-purpose MCP tool that helps LLMs structure reasoning steps. It's good for:
- Breaking down complex problems
- Step-by-step analysis
- General problem-solving

**wiki_explain** is domain-specific for wiki articles. It's more efficient because:
- Returns structured article metadata instantly
- No need for multiple reasoning steps
- Provides concrete suggestions (add headers, fix errors, etc.)
- Shows quality metrics, validation status, and structure analysis

**When to use wiki_explain:**
- Before editing: "Explain the Docker article so I know what to update"
- After creating: "Explain my new article to see if it's well-structured"
- For audit: "Explain all articles with validation errors"

**Example wiki_explain output:**
```
📊 Article Analysis: "Docker Deployment Guide"

Quality Metrics
- Quality Score: 0.85/1.0
- Word Count: 450
- Classification: tutorial
- Validation: ✅ Valid

Structure
- Headers: 4
- Code Blocks: 2
- Images: 1
- External Links: 3

💡 Suggestions
- Add more tags for better discoverability
- Consider adding a mermaid diagram for architecture
```

### wiki_validate Output

Checks:
- **Spelling**: Common misspellings + tech terms
- **Markdown**: Unclosed code blocks, broken links, header syntax
- **Mermaid**: Diagram syntax errors, unclosed brackets
- **Code**: JS/Python/Bash syntax checks
- **Links**: Spaces in URLs, placeholders

Returns:
- Quality score (0-1.0)
- Error count with fixes
- Warning count with suggestions

## Comparison: Help Endpoint vs Explanation Tool

| Approach | Pros | Cons |
|----------|------|------|
| **Help Endpoint** (API docs) | Static reference, always available | Not contextual, requires manual lookup |
| **wiki_explain Tool** | Contextual, interactive, actionable | Requires function call |
| **Sequential Thinking** | General reasoning, flexible | Slower, more tokens, generic output |

**Recommendation:** `wiki_explain` is more efficient than Sequential Thinking for wiki operations because:
1. **Purpose-built**: Designed specifically for article analysis
2. **Structured output**: Returns JSON-ready data, not freeform text
3. **Actionable**: Gives concrete suggestions ("Add 2 more headers")
4. **Fast**: Single function call vs multiple reasoning steps
5. **Integrated**: Works with validation, quality scoring, and enhancement systems

Sequential Thinking is better for open-ended exploration, while wiki_explain is optimized for documentation workflows.
