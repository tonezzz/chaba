# Wiki Documentation Policy

## 📋 Policy Statement

**Effective Date:** April 2026  
**Applies To:** All technical documentation, guides, and knowledge artifacts

All project documentation **must** be migrated to the **MCP Wiki** (`http://localhost:3008`) as the primary source of truth. Local markdown files in `/docs` are deprecated and should be considered temporary staging only.

---

## 🎯 Migration Strategy

### Phase 1: Immediate (This Week)
- [ ] Create wiki articles for all existing `/docs/*.md` files
- [ ] Update README.md to point to wiki for detailed docs
- [ ] Add wiki links in code comments where relevant

### Phase 2: Ongoing (New Policy)
- **All new documentation** → Create directly in wiki
- **Code changes** → Update wiki articles, not markdown files
- **Design decisions** → Document in wiki with "Decision Log" tag

### Phase 3: Deprecation (Next Month)
- Archive `/docs/*.md` files (move to `/docs/archive/`)
- Keep only `WIKI_POLICY.md` and `README.md` in `/docs`

---

## 📚 Wiki Article Structure

### Required Tags
Every article **must** have at least one category tag:
- `architecture` - System design, component diagrams
- `guide` - How-to guides, tutorials
- `api` - API documentation, endpoints
- `decision-log` - ADRs, design decisions
- `troubleshooting` - Debugging guides, common issues
- `reference` - Quick reference, cheatsheets
- `policy` - Project policies, conventions

### Title Convention
```
[Type]: [Subject] - [Context if needed]

Examples:
- "Guide: Docker Compose Setup"
- "API: AutoAgent Research Endpoints"
- "Decision: Move Docs to Wiki (April 2026)"
- "Troubleshooting: Free Model Connection Issues"
```

### Content Template
```markdown
## Summary
One-paragraph overview of what this article covers.

## Details
### Subsection 1
...

### Subsection 2
...

## Related
- [[Other Article Title]]
- [[Another Article]]

## Metadata
- Created: YYYY-MM-DD
- Author: @username
- Status: draft|active|archived
- Tags: tag1, tag2, tag3
```

---

## 🛠️ How to Migrate

### Option 1: Web UI (One-off)
1. Go to http://localhost:3008/new
2. Enter title (follow convention)
3. Copy content from markdown file
4. Add appropriate tags
5. Create article

### Option 2: Script (Batch)
```bash
# Run from chaba root
python scripts/migrate-docs-to-wiki.py
```

### Option 3: Smart Research (Auto)
```bash
# Creates wiki article via smart-research
python /workspace/smart-research.py "Document [Topic]"
```

---

## 🔍 Search & Discovery

### Finding Articles
- **Browse:** http://localhost:3008
- **Search:** Use search box on wiki home
- **Cross-refs:** Click `[[Article Name]]` links

### Cross-Referencing
Always link related articles:
```markdown
See also: [[Related Article Title]]
Part of: [[Architecture Overview]]
```

---

## 📝 Documentation Standards

### Keep Updated
- Review articles quarterly
- Update when code changes
- Mark stale articles with `status: outdated` tag

### Version Control
- Wiki tracks all changes via `updated_at`
- Major revisions: Add "Changelog" section
- Breaking changes: Create new article, link old

### Code Examples
- Include working, tested code
- Add language tag to code blocks
- Reference line numbers if specific

---

## 🚫 What NOT to Document in Wiki

| Use Wiki For | Don't Use Wiki For |
|-------------|-------------------|
| Architecture decisions | Source code (keep in git) |
| API documentation | Configuration files |
| Troubleshooting guides | Secrets/credentials |
| Design patterns | Temporary notes |
| Project policies | Personal todos |

---

## 🔄 Migration Checklist

### Current Docs → Wiki

| File | Wiki Title | Tags | Status |
|------|-----------|------|--------|
| `MODULARIZATION_GUIDE.md` | "Guide: Project Modularization" | `architecture,guide,modularization` | ⬜ |
| `MODULARIZATION_STATUS.md` | "Status: Modularization Progress" | `status,modularization` | ⬜ |
| `MODULARIZATION_STRATEGY.md` | "Decision: Modularization Strategy" | `decision-log,architecture` | ⬜ |
| `MODULARIZATION_TROUBLESHOOTING.md` | "Troubleshooting: Modularization Issues" | `troubleshooting,modularization` | ⬜ |
| `mcp_wiki.md` | "Reference: MCP Wiki Usage" | `reference,mcp,wiki` | ⬜ |

### AutoAgent Research Articles
- [x] "What Is Gemini Live Api" (auto-created)
- [x] "What Is Claude 3.7 Sonnet" (auto-created)
- [x] "What Is Mcp Protocol" (auto-created)
- [x] "What Is Docker Compose" (auto-created)
- [ ] "Guide: Smart Research Usage"

---

## 📣 Communication

### Announce Changes
When creating significant articles:
1. Post in team chat with wiki link
2. Add `announcement` tag to article
3. Link from relevant code PRs

### Request Reviews
For policy/architecture articles:
1. Create with `status: draft` tag
2. Share link for feedback
3. Update to `status: active` after approval

---

## 🔐 Access & Permissions

### Current Setup
- **URL:** http://localhost:3008
- **API:** http://localhost:3008/api
- **No auth required** (local development)

### Future: Production
- Will add basic auth or VPN-only access
- Migration script will handle auth headers

---

## 📊 Success Metrics

Track monthly:
- Total articles in wiki
- Articles created via smart-research
- Most-viewed articles (when analytics added)
- Docs deleted from `/docs` folder

---

## 🆘 Questions?

- **Wiki down?** Check: `docker ps | grep mcp-wiki`
- **Can't save?** Verify network: `curl http://localhost:3008/health`
- **Need help?** Ask in team chat, tag with `#wiki`

---

**Last Updated:** 2026-04-10  
**Policy Owner:** @chaba  
**Review Cycle:** Quarterly
