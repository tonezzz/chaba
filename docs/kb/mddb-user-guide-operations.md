---
category: operations
---

# Operational Procedures

### Adding New Documentation

**SSOT Configuration**:
1. Create new YAML file in appropriate SSOT directory
2. Follow SSOT documentation standards
3. File watcher automatically syncs to MDDB
4. Document becomes searchable immediately

**KB Entries**:
1. Create KB entry in `docs/kb/` directory
2. Follow KB template and standards
3. Run manual sync or wait for periodic sync
4. Document becomes searchable via MDDB

**General Documentation**:
1. Add documentation to appropriate directory
2. Follow project documentation standards
3. Run migration script if needed
4. Document becomes searchable via MDDB

### Updating Existing Documentation

**SSOT Updates**:
1. Edit YAML file directly
2. Save changes
3. File watcher syncs automatically
4. Changes reflected in search immediately

**KB Updates**:
1. Edit KB entry directly
2. Save changes
3. Run manual sync or wait for periodic sync
4. Changes reflected in search

**General Documentation Updates**:
1. Edit documentation file directly
2. Save changes
3. Run migration script if needed
4. Changes reflected in search

### Troubleshooting

**MDDB Not Responding**:
```bash
# Check container status
docker ps | grep mddb

# Check container logs
docker logs mddb -n 50

# Restart container
cd /home/tony/CascadeProjects/chaba-kbman/stacks/web/mddb
docker compose restart mddb

# Check health endpoint
curl -s http://tony-omen.local:11023/health
```

**SSOT Auto-Sync Not Working**:
```bash
## Performance and Quality

**Search Performance**:
- **Relevance Scores**: 0.45-0.80 (high quality semantic understanding)
- **Response Times**: 88-550ms (fast real-time search)
- **Collections**: 13 collections (154+ documents)
- **Embeddings**: Ollama nomic-embed-text (768 dimensions)
- **Algorithm**: Flat with cosine distance metric

**System Resources**:
- **Database Size**: ~50MB (245 documents, 277 revisions)
- **Memory Usage**: 3.5M for file watcher service
- **CPU Usage**: Minimal for search operations
- **Disk Usage**: Efficient storage with indexing

## Best Practices

### SSOT Editing
- **Always edit YAML directly** - this is the primary workflow
- **Follow SSOT documentation standards** for consistency
- **Test changes in staging if available** before production
- **Monitor sync service** to ensure changes propagate
- **Keep YAML structure clean** and well-formatted

### Search Usage
- **Use semantic search** for broad queries and exploration
- **Filter by collection** for targeted searches
- **Use specific terms** for better relevance
- **Check metadata** for source and collection information
- **Leverage MCP integration** for AI-assisted searches

### System Maintenance
- **Monitor health status** via mcp-health
- **Check service logs** regularly for issues
- **Update documentation** as system evolves
- **Backup configuration** and SSOT files regularly
- **Test sync functionality** after changes

