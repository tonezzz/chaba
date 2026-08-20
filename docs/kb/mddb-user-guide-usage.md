---
category: operations
---

# Edit SSOT configuration
vim /home/tony/CascadeProjects/chaba/docs/ssot/infrastructure/ssot.health.yml

# Make changes and save
# File watcher detects change within 2 seconds
# Sync script updates MDDB automatically
# Changes are now searchable via MDDB
```

### Automatic MDDB Sync

**Mechanism**: File watcher (`watch-ssot-sync.py`) monitors SSOT directory

**Service**: `ssot-sync.service` (systemd background service)

**Trigger**: YAML file modifications trigger sync within 2 seconds

**Transparency**: Sync is automatic and transparent to editing workflow

**Verification**:
```bash
# Check service status
systemctl status ssot-sync.service

# View recent sync activity
journalctl -xeu ssot-sync.service -n 20

# Manual sync test
cd /home/tony/CascadeProjects/chaba-kbman
python3 scripts/sync-ssot-to-mddb.py
```

### MDDB Search Interface

**Purpose**: MDDB provides semantic search across SSOT content

**Benefits**:
- AI-powered search with Ollama embeddings (nomic-embed-text)
- Semantic understanding of content (not just keyword matching)
- High relevance scores (0.45-0.80)
- Fast response times (88-550ms)

**Access Methods**:
1. **Web UI**: http://tony-omen.local:3002/
2. **MCP Integration**: mddb server (http://localhost:9001)
3. **REST API**: http://tony-omen.local:11023/

**Search Usage**:
```bash
# Health check
curl -s http://tony-omen.local:11023/health

# Vector search
curl -X POST http://tony-omen.local:11023/v1/vector-search \
  -H "Content-Type: application/json" \
  -d '{"query":"health check configuration","limit":3}'

# Get statistics
curl -s http://tony-omen.local:11023/v1/vector-stats
```

**Best For**:
- Scripting and automation
- Integration with external tools
- Health monitoring
- Administrative operations

# Check service status
systemctl status ssot-sync.service

# Check service logs
journalctl -xeu ssot-sync.service -n 50

# Restart service
systemctl restart ssot-sync.service

# Manual sync test
cd /home/tony/CascadeProjects/chaba-kbman
python3 scripts/sync-ssot-to-mddb.py
```

**Search Not Finding Content**:
```bash
# Check SSOT files exist
find /home/tony/CascadeProjects/chaba/docs/ssot -name '*.yml'

# Check MDDB collections
curl -s http://tony-omen.local:11023/v1/vector-stats

# Reindex specific collection
curl -X POST http://tony-omen.local:11023/v1/vector-reindex \
  -H "Content-Type: application/json" \
  -d '{"collection":"ssot-infrastructure","force":true}'
```

