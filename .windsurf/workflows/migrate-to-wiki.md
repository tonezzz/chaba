---
description: Migrate documentation to MCP Wiki
---

# Migrate Documentation to Wiki

## Quick Start

1. **One-time setup:** Ensure mcp-wiki is running
   ```bash
   cd stacks/pc1-wiki && docker-compose up -d
   ```

2. **Migrate a single file:**
   ```bash
   // turbo
   python scripts/migrate-docs-to-wiki.py docs/MODULARIZATION_GUIDE.md
   ```

3. **Migrate all docs:**
   ```bash
   // turbo
   python scripts/migrate-docs-to-wiki.py
   ```

4. **Verify:** Open http://localhost:3008 and check articles

## Full Migration Process

### Step 1: Pre-Migration Check
```bash
# Check wiki is running
curl -s http://localhost:3008/health | grep -q "ok" && echo "✅ Wiki ready" || echo "❌ Start wiki first"

# Check current articles
curl -s http://localhost:3008/api/articles | wc -c
```

### Step 2: Run Migration
```bash
cd c:\chaba
python scripts/migrate-docs-to-wiki.py
```

### Step 3: Post-Migration Review
1. Visit http://localhost:3008
2. Review each article:
   - Check title format: `[Type]: [Subject]`
   - Verify tags are appropriate
   - Add cross-references: `[[Related Article]]`
3. Update status tags: `status: active` or `status: draft`

### Step 4: Update README
```markdown
## Documentation
📚 [View Wiki](http://localhost:3008) - Primary documentation  
📋 [Documentation Policy](../docs/WIKI_DOCUMENTATION_POLICY.md)
```

### Step 5: Archive Old Files
```bash
// turbo
mkdir -p docs/archive
mv docs/MODULARIZATION_*.md docs/archive/
mv docs/mcp_wiki.md docs/archive/
```

## Migration Rules

| File Pattern | Wiki Title Format | Tags |
|-------------|-------------------|------|
| `*_GUIDE.md` | `Guide: [Name]` | `guide` |
| `*_TROUBLESHOOTING.md` | `Troubleshooting: [Name]` | `troubleshooting` |
| `*_STRATEGY.md` | `Decision: [Name]` | `decision-log` |
| `*_STATUS.md` | `Status: [Name]` | `status` |
| `*_POLICY.md` | `Policy: [Name]` | `policy` |
| Other | `Reference: [Name]` | `reference` |

## Troubleshooting

### "Connection refused" Error
```bash
# Start the wiki service
cd stacks/pc1-wiki && docker-compose up -d

# Or use external API URL
export WIKI_API_URL=http://mcp-wiki:8080  # From inside containers
```

### Article Already Exists
- Script skips duplicates (shows ⚠️)
- To update: Edit directly in wiki UI
- Or delete first, then re-run

### Tags Missing
- Add manually via wiki edit UI
- Or modify `infer_tags()` in migration script

## New Documentation Workflow

### Going Forward (No More Markdown Files)

1. **Create directly in wiki:**
   - Go to http://localhost:3008/new
   - Follow title convention: `[Type]: [Subject]`
   - Add appropriate tags
   - Use template from policy doc

2. **Or use smart-research:**
   ```bash
   python /workspace/smart-research.py "Document [Topic]"
   ```

3. **Cross-reference existing docs:**
   ```markdown
   ## Related
   - [[Architecture Overview]]
   - [[API Endpoints]]
   ```

## Policy Reminder

> All new documentation **must** go to wiki.  
> See: `docs/WIKI_DOCUMENTATION_POLICY.md`
