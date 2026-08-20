---
category: operations
---

# Related Documentation

- **MDDB Implementation**: docs/kb/mddb-implementation-complete.md
- **Multi-Project Implementation**: docs/kb/mddb-multi-project-implementation.md
- **SSOT-MDDB Integration**: docs/kb/ssot-mddb-integration-assessment.md
- **SSOT Documentation Standards**: docs/kb/ssot-documentation-standards.md
- **Documentation Maintenance Standards**: docs/kb/documentation-maintenance-standards.md

## Configuration

### MDDB Configuration
Located in `stacks/web/mddb/docker-compose.yml` and accessed via:
- **Web UI**: http://tony-omen.local:3002/
- **MCP Integration**: mddb server (http://localhost:9001)
- **REST API**: http://tony-omen.local:11023/

### SSOT Auto-Sync Configuration
Located in `/home/tony/CascadeProjects/chaba-kbman/scripts/`:
- **File Watcher**: watch-ssot-sync.py (monitors docs/ssot/ directory)
- **Sync Script**: sync-ssot-to-mddb.py (syncs YAML to MDDB)
- **Systemd Service**: ssot-sync.service (background auto-sync)

## Performance

**MDDB Semantic Search**:
- **Relevance Scores**: 0.45-0.80 (high quality semantic understanding)
- **Response Times**: 88-550ms (fast real-time search)
- **Collections**: 20 collections (340+ documents)
- **Embeddings**: Ollama nomic-embed-text (768 dimensions)
- **Algorithm**: Flat with cosine distance metric

## Troubleshooting

### MDDB not responding
**Check MDDB container status**:
```bash
docker ps | grep mddb
docker logs mddb -n 50
```

**Check MDDB health endpoint**:
```bash
curl -s http://tony-omen.local:11023/health
```

**Restart MDDB if needed**:
```bash
cd /home/tony/CascadeProjects/chaba-kbman/stacks/web/mddb
docker compose restart mddb
```

### SSOT auto-sync not working
**Check file watcher service**:
```bash
systemctl --user status ssot-sync.service
```

**Check service logs**:
```bash
journalctl --user -xeu ssot-sync.service -n 50
```

**Restart file watcher**:
```bash
systemctl --user restart ssot-sync.service
```

**Manual sync test**:
```bash
cd /home/tony/CascadeProjects/chaba-kbman
python3 scripts/sync-ssot-to-mddb.py
```

### Search not finding SSOT content
**Check SSOT files exist**:
```bash
find /home/tony/CascadeProjects/chaba/docs/ssot -name '*.yml'
```

**Check MDDB SSOT collections**:
```bash
curl -s http://tony-omen.local:11023/v1/vector-stats
```

**Reindex SSOT collections**:
```bash
curl -X POST http://tony-omen.local:11023/v1/vector-reindex \
  -H "Content-Type: application/json" \
  -d '{"collection":"ssot-infrastructure","force":true}'
```

### Assistant workflow guidelines
**When performing documentation searches:**
1. **Primary choice**: Use MDDB semantic search via MCP (`mcp_call_tool mddb semantic_search`)
2. **Secondary choice**: Use SSOT pattern matching (via ssot-search skill) for exact YAML searches
3. **Tertiary choice**: Fall back to the MCP docs server (`@devista/docs-mcp`) only if MDDB is unavailable or fails, with user confirmation per Service Failure and Fallback Procedures
4. **Traditional tools**: Only use grep/read/find after attempting the above and identifying the specific issue
5. **Never silently fall back** without explaining the issue and proposed fix

## Related Documentation

- **MDDB Implementation**: docs/kb/mddb-implementation-complete.md
- **Multi-Project Implementation**: docs/kb/mddb-multi-project-implementation.md
- **SSOT-MDDB Integration**: docs/kb/ssot-mddb-integration-assessment.md
- **SSOT Documentation Standards**: docs/kb/ssot-documentation-standards.md
- **Documentation Maintenance Standards**: docs/kb/documentation-maintenance-standards.md

