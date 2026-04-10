# idc1-db Migration Guide

Migrating services from local SQLite to shared PostgreSQL on idc1.

## Overview

| Service | Before (Local) | After (Shared) |
|---------|---------------|----------------|
| autoagent-test | SQLite file | PostgreSQL on idc1 |
| mcp-wiki (pc1) | SQLite file | SQLite (local) OR PostgreSQL (shared) |

## Prerequisites

1. **VPN Connection**: Ensure pc1 is connected to idc1 VPN
2. **idc1-db Deployed**: PostgreSQL stack running on idc1
3. **Network Access**: Containers can reach `idc1.surf-thailand.com:5432`

## Migration Steps

### 1. Verify idc1-db is Running

```bash
# On idc1
ssh chaba@idc1.surf-thailand.com
docker ps | grep postgres

# Test from pc1 (Windows PowerShell)
Test-NetConnection idc1.surf-thailand.com -Port 5432
```

### 2. Migrate autoagent-test

The autoagent-test stack is already configured to use PostgreSQL:

```bash
# On pc1 (Windows PowerShell)
cd C:\chaba\stacks\autoagent-test

# Rebuild with PostgreSQL support
docker-compose build --no-cache

# Start with new configuration
docker-compose up -d

# Verify connection
docker logs autoagent-test | Select-String -Pattern "PostgreSQL|database"
```

**Key changes**:
- `DATABASE_URL` points to idc1-db
- `postgres_kb.py` provides PostgreSQL KB interface
- VPN network attached for connectivity

### 3. Migrate mcp-wiki (Optional)

By default, pc1-wiki keeps local SQLite. To use shared PostgreSQL:

```bash
# Edit docker-compose.yml
cd C:\chaba\stacks\pc1-wiki

# Uncomment PostgreSQL lines in docker-compose.yml:
# WIKI_USE_POSTGRES: '1'
# DATABASE_URL: postgresql://chaba:changeme@idc1.surf-thailand.com:5432/chaba

# Rebuild and restart
docker-compose up -d --build
```

## Network Configuration

### VPN Access Required

Both services need VPN network access to reach idc1:

```yaml
# In docker-compose.yml
networks:
  - default
  - vpn

networks:
  vpn:
    external: true
    name: idc1-stack_vpn
```

### Verify Network Connectivity

```bash
# From autoagent container
docker exec -it autoagent-test bash
ping idc1.surf-thailand.com
psql postgresql://chaba:changeme@idc1.surf-thailand.com:5432/chaba -c "SELECT version();"
```

## Testing the Migration

### Test 1: Knowledge Base Operations

```bash
# Inside autoagent container
cd /app
python3 -c "
from postgres_kb import PostgresKnowledgeBase
import os

kb = PostgresKnowledgeBase(os.getenv('DATABASE_URL'))

# Create test article
result = kb.create_article(
    title='Test Migration',
    content='Testing PostgreSQL migration from pc1',
    tags=['test', 'migration'],
    classification='test'
)
print(f'Created: {result}')

# Search
results = kb.search('migration', limit=5)
print(f'Found: {len(results)} articles')
for r in results:
    print(f'  - {r[\"title\"]}')
"
```

### Test 2: Cross-Host Consistency

```bash
# From pc1 - create article via autoagent
# From idc1 - verify in PostgreSQL
ssh chaba@idc1.surf-thailand.com
docker exec -it idc1-postgres psql -U chaba -d chaba -c "SELECT title, updated_at FROM kb_articles ORDER BY updated_at DESC LIMIT 5;"
```

## Rollback Plan

If issues occur, revert to local SQLite:

### autoagent-test Rollback

```bash
cd C:\chaba\stacks\autoagent-test

# Switch to local SQLite
docker-compose down
# Edit smart-research.py to force HTTP mode
# Or set USE_POSTGRES=0 in .env
docker-compose up -d
```

### mcp-wiki Rollback

```bash
cd C:\chaba\stacks\pc1-wiki

# Revert to SQLite
docker-compose down
# Comment out WIKI_USE_POSTGRES and DATABASE_URL in docker-compose.yml
docker-compose up -d
```

## Troubleshooting

### Connection Refused

```bash
# Check if PostgreSQL is listening on all interfaces
ssh chaba@idc1.surf-thailand.com
docker exec idc1-postgres netstat -tlnp | grep 5432
# Should show 0.0.0.0:5432, not 127.0.0.1:5432
```

### Authentication Failed

```bash
# Verify credentials
docker exec -it idc1-postgres psql -U chaba -d chaba -c "SELECT 1;"

# Reset password if needed
docker exec -it idc1-postgres psql -U postgres -c "ALTER USER chaba WITH PASSWORD 'newpassword';"
```

### VPN Not Reachable

```bash
# On pc1 - check WireGuard connection
wg show

# Should show handshake with idc1
# Latest handshake: X seconds/minutes ago
```

## Post-Migration

After successful migration:

1. **Update documentation** in wiki about shared database
2. **Backup strategy** - PostgreSQL dumps from idc1
3. **Monitor connections** - Watch for VPN issues
4. **Consider failover** - Local SQLite as backup mode

## Connection Reference

| From | To | Connection String |
|------|-----|-------------------|
| autoagent-test (pc1) | idc1-db | `postgresql://chaba:pass@idc1.surf-thailand.com:5432/chaba` |
| mcp-wiki (pc1, optional) | idc1-db | `postgresql://chaba:pass@idc1.surf-thailand.com:5432/chaba` |
| Local tools (pc1) | idc1-db | Same, requires VPN |

## Files Changed

- `stacks/idc1-db/` - PostgreSQL stack
- `stacks/autoagent-test/docker-compose.yml` - Added VPN network
- `stacks/autoagent-test/.env` - PostgreSQL connection
- `stacks/autoagent-test/Dockerfile` - Added psycopg2
- `stacks/autoagent-test/postgres_kb.py` - New PostgreSQL KB module
- `stacks/autoagent-test/smart-research.py` - Dual-mode support
- `mcp/mcp-wiki/index.js` - Dual SQLite/PostgreSQL support
- `mcp/mcp-wiki/package.json` - Added pg dependency
- `stacks/pc1-wiki/docker-compose.yml` - Optional PostgreSQL mode
