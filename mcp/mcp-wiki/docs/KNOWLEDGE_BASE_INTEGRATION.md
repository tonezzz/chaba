# Knowledge Base Integration with AutoAgent

This document describes how to use `mcp_wiki` as a knowledge base for AutoAgent research.

## Overview

The knowledge base integration creates a self-improving research system:

1. **Research** → Query free models via OpenRouter
2. **Store** → Save results to SQLite wiki database
3. **Retrieve** → Check existing knowledge before researching
4. **Reuse** → Build upon previous findings

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  User Query     │────▶│  Wiki Knowledge  │────▶│  Check Existing │
│                 │     │     Base         │     │   Knowledge     │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                                │                           │
                                │ Cache Hit                 │ Cache Miss
                                ▼                           ▼
                        ┌──────────────┐          ┌──────────────────┐
                        │ Return Saved │          │   Free Model     │
                        │   Article    │          │   Research       │
                        └──────────────┘          └──────────────────┘
                                                            │
                                                            ▼
                                                    ┌──────────────┐
                                                    │ Save to Wiki │
                                                    │  for Future  │
                                                    └──────────────┘
```

## Components

### 1. wiki-knowledge.py

Main integration script with two modes:

**Mode A: Research with Knowledge Check**
```bash
python wiki-knowledge.py "What is Gemini Live API?"
```
- Checks wiki for existing articles
- If found: returns cached result
- If not found: researches with free model + saves to wiki

**Mode B: Force Fresh Research**
```bash
python wiki-knowledge.py "What is Gemini Live API?" --no-cache
```
- Skips cache check
- Always does fresh research

**Mode C: Research Without Saving**
```bash
python wiki-knowledge.py "What is Gemini Live API?" --no-save
```
- Researches but doesn't save to wiki

### 2. Database Schema

**articles table:**
```sql
id INTEGER PRIMARY KEY
title TEXT UNIQUE NOT NULL
content TEXT NOT NULL
tags TEXT
created_at DATETIME
updated_at DATETIME
```

**research_sessions table:**
```sql
id INTEGER PRIMARY KEY
query TEXT NOT NULL
model_used TEXT
article_title TEXT
created_at DATETIME
```

### 3. WikiKnowledgeBase Class

Python interface for knowledge operations:

```python
from wiki-knowledge import WikiKnowledgeBase

wiki = WikiKnowledgeBase()

# Search existing knowledge
results = wiki.search("gemini api", limit=5)

# Save new knowledge
wiki.save_article(
    title="Gemini Live API Overview",
    content="...",
    tags=["research", "google", "ai", "api"]
)

# Retrieve specific article
article = wiki.get_article("Gemini Live API Overview")

# List by tag
articles = wiki.list_articles(tag="api")
```

## Usage Examples

### Basic Research with Auto-Caching

```bash
cd /workspace
python wiki-knowledge.py "What is the difference between GPT-4 and Claude?"
```

Output:
```
🔍 Checking wiki for: What is the difference between GPT-4 and Claude?
🔬 Researching with nvidia/nemotron-3-super-120b-a12b:free...
✅ Saved to wiki: What Is The Difference Between Gpt-4 And Claude
```

### Using Cached Result

Run the same query again:
```bash
python wiki-knowledge.py "What is the difference between GPT-4 and Claude?"
```

Output:
```
🔍 Checking wiki for: What is the difference between GPT-4 and Claude?
✅ Found 1 existing articles:
  1. What Is The Difference Between Gpt-4 And Claude (updated: 2024-01-15 10:30:00)

📚 Using existing knowledge: What Is The Difference Between Gpt-4 And Claude
```

### Browse Knowledge Base

```bash
python wiki-knowledge.py
```

Shows:
```
📚 Existing Knowledge Base:
==================================================
  • What Is The Difference Between Gpt-4 And Claude [research, ai-model]
  • Gemini Live Api Overview [research, api, google]
  • Openrouter Free Models List [research, api, models]
```

## Integration with AutoAgent Runner

Add to `control-server.py` runner panel:

```html
<span class="preset" onclick='setFreeCommand("python /workspace/wiki-knowledge.py ")'>
    📚 Wiki Research (Auto-Cache)
</span>
```

## Benefits

### 1. **Cost Savings**
- Cached results = zero API cost
- Free models for new research
- Pay only for novel queries

### 2. **Speed**
- Cached results: instant (< 1 second)
- Fresh research: 30-120 seconds

### 3. **Knowledge Accumulation**
- Each research enriches the base
- Build comprehensive knowledge over time
- Cross-reference previous findings

### 4. **Consistency**
- Same query = same structured answer
- Maintains research quality standards
- Version history via updated_at

## Advanced Usage

### Building Topic Collections

Research related topics to build comprehensive knowledge:

```bash
# Build "AI APIs" collection
python wiki-knowledge.py "OpenAI API capabilities"
python wiki-knowledge.py "Anthropic Claude API features"
python wiki-knowledge.py "Google Gemini API endpoints"
python wiki-knowledge.py "Cohere API use cases"

# Query collection
python wiki-knowledge.py
# Shows all with [api] tag
```

### Research Chains

Use previous research as foundation:

```bash
# Step 1: General overview
python wiki-knowledge.py "What is LLM fine-tuning?"

# Step 2: Specific technique  
python wiki-knowledge.py "What is LoRA fine-tuning?"

# Step 3: Implementation
python wiki-knowledge.py "How to implement LoRA with Hugging Face?"
```

### Knowledge Export

Export wiki to share or backup:

```python
import sqlite3
import json

conn = sqlite3.connect('/data/wiki.db')
conn.row_factory = sqlite3.Row

cursor = conn.cursor()
cursor.execute('SELECT title, content, tags, updated_at FROM articles')

articles = [dict(row) for row in cursor.fetchall()]

with open('knowledge-export.json', 'w') as f:
    json.dump(articles, f, indent=2)
```

## Configuration

### Environment Variables

```bash
# Wiki database location
WIKI_DB_PATH=/data/wiki.db

# Wiki HTTP port (for mcp_wiki server)
WIKI_HTTP_PORT=8082

# OpenRouter API key
OPENROUTER_API_KEY=sk-or-v1-...
```

### Docker Compose Integration

Add volume for persistent knowledge:

```yaml
services:
  autoagent-test:
    volumes:
      - autoagent-workspace:/workspace
      - wiki-data:/data  # Persistent wiki storage
      
volumes:
  wiki-data:
    driver: local
```

## Best Practices

### 1. **Use Descriptive Titles**
Good: `"GPT-4 Vision API Multimodal Capabilities"`
Bad: `"API Info"`

### 2. **Tag Consistently**
Common tags:
- `research` - All auto-generated
- `api` - API-related
- `ai-model` - Specific models
- `tutorial` - How-to guides
- `comparison` - vs/comparison content

### 3. **Periodically Refresh**
Some knowledge gets stale:
```bash
# Update with fresh research
python wiki-knowledge.py "Gemini API latest features 2024" --no-cache
```

### 4. **Cross-Reference**
Link related articles in content:
```markdown
See also: [[Claude API Overview]] for comparison.
```

## Future Enhancements

### Potential Features

1. **Semantic Search**
   - Use embeddings for better matching
   - Find related articles by meaning, not just keywords

2. **Knowledge Graph**
   - Extract entities and relationships
   - Visualize connections between topics

3. **Auto-Summarization**
   - Generate executive summaries
   - Create topic overviews from multiple articles

4. **Multi-Modal Support**
   - Store images, code snippets
   - Link to external resources

5. **Collaborative Editing**
   - Manual article improvements
   - Comment and annotation system

## Troubleshooting

### "No such table: articles"
Run wiki-knowledge.py once to initialize database schema.

### "Permission denied" on /data/wiki.db
Ensure volume permissions:
```bash
docker exec autoagent-test chmod 777 /data
```

### Slow search with many articles
Add FTS5 index for full-text search (future enhancement).

## Summary

The knowledge base integration transforms AutoAgent from a stateless tool into a learning system that:

- ✅ Remembers past research
- ✅ Avoids redundant API calls
- ✅ Builds comprehensive knowledge over time
- ✅ Provides instant answers for known topics
- ✅ Maintains research quality and structure

Start building your knowledge base today!
