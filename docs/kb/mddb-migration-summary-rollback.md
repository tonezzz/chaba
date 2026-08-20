---
category: operations
---

# Rollback Procedures

### KB Rollback
```bash
# Restore original KB from archive
cd /home/tony/CascadeProjects/chaba-kbman
tar -xzf docs/kb-backup-2026-08-12.tar.gz

# Stop MDDB services
cd stacks/web/mddb
docker compose down

# Restore old documentation search methods
# (Reinstall docs MCP if needed)
```

### SSOT Rollback
```bash
# Stop file watcher service
systemctl stop ssot-sync.service
systemctl disable ssot-sync.service

# SSOT YAML files remain editable (no changes needed)
# MDDB sync simply stops
```

### Complete System Rollback
```bash
# Stop all MDDB services
cd /home/tony/CascadeProjects/chaba-kbman/stacks/web/mddb
docker compose down

# Restore original KB
tar -xzf docs/kb-backup-2026-08-12.tar.gz

# Restore MCP configuration
# (Revert mcp_config.json changes)

# Restart legacy services if needed
```

