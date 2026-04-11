# idc1-db Stack - Todo List

## Current Status
- [x] Stack redeployed with sqlite-web container removed
- [x] All services defined in docker-compose.yml
- [x] Script created to save documentation to wiki (`scripts/save-idc1-db-docs-to-wiki.py`)
- [x] Documentation saved to wiki (15 articles total)
- [x] **EXECUTE ON IDC1**: Data migrated from pc1 SQLite to idc1 PostgreSQL (12 articles)
- [x] **EXECUTE ON IDC1**: Fix pgadmin container (email validation issue)
- [x] **EXECUTE ON IDC1**: Verify all containers running

## Services Overview

| Service | Image | Port | Status |
|---------|-------|------|--------|
| postgres | postgres:15-alpine | 5432 | ✅ Up (healthy) |
| mcp-wiki | ghcr.io/tonezzz/mcp-wiki:latest | 3008 | ✅ Up |
| autoagent | ghcr.io/tonezzz/autoagent:latest | 8059/8058 | ✅ Up |
| pgadmin | dpage/pgadmin4:latest | 5050 | ✅ Up |
| mcp-postgres | mcp/postgres:latest | - | ⏸️ Not deployed (profile) |
| redis | redis:7-alpine | 6379 | ⏸️ Not deployed |
| weaviate | semitechnologies/weaviate:1.25.0 | 8082 | ⏸️ Not deployed |

## Verification Commands (run on idc1)

```bash
# Check container status
docker ps --filter "name=idc1-" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Verify all 5 containers
cd /home/chaba/chaba/stacks/idc1-db
docker compose ps

# Check logs
docker logs idc1-postgres --tail 20
docker logs idc1-mcp-wiki --tail 20
docker logs idc1-autoagent --tail 20
docker logs idc1-pgadmin --tail 10

# Test endpoints
curl -s http://localhost:3008/api/articles | head -5
curl -s http://localhost:8059/health 2>/dev/null || echo "AutoAgent check"
```

## Data Migration Steps

### Prerequisites
1. Ensure VPN connection from pc1 to idc1 is active
2. Confirm PostgreSQL is accessible at idc1.surf-thailand.com:5432
3. Get pgAdmin credentials from .env on idc1

### Migration Options

**Option A: PowerShell Script (Recommended)**
```powershell
# On pc1 (Windows)
cd c:\chaba
./scripts/migrate-to-idc1-db.ps1
```

**Option B: Manual Migration**
1. Export from pc1 SQLite:
   ```bash
   sqlite3 c:/chaba/stacks/pc1-wiki/wiki.db ".dump articles" > articles.sql
   ```
2. Import to idc1 PostgreSQL via pgAdmin or psql
3. See `MIGRATION_GUIDE.md` for detailed steps

## Documentation to Save on idc1 Wiki

After migration is complete, save these articles to the wiki:
- [x] Service endpoints reference
- [x] Migration guide  
- [x] Stack README

### Automated Script

```bash
# From repo root on idc1
python scripts/save-idc1-db-docs-to-wiki.py

# Dry run (preview only)
python scripts/save-idc1-db-docs-to-wiki.py --dry-run

# Custom wiki URL
python scripts/save-idc1-db-docs-to-wiki.py --wiki-api http://localhost:3008
```

### Manual API Example

```bash
# Save via API directly
curl -X POST http://idc1.surf-thailand.com:3008/api/articles \
  -H "Content-Type: application/json" \
  -d '{"title":"IDC1-DB Service Endpoints","content":"..."}'
```

## Files in this Stack

- `docker-compose.yml` - Full stack definition (PostgreSQL, pgAdmin, mcp-wiki, autoagent)
- `.env.example` - Environment variable template
- `README.md` - Stack documentation
- `MIGRATION_GUIDE.md` - Detailed migration instructions
- `init/` - PostgreSQL initialization scripts

## Notes

- GitHub Actions workflow at `.github/workflows/build-idc1-db-images.yml` builds images on push to `idc1-db` branch
- Images published to `ghcr.io/tonezzz/mcp-wiki:latest` and `ghcr.io/tonezzz/autoagent:latest`
- AutoAgent on idc1 uses PostgreSQL for knowledge base (not SQLite)
- mcp-wiki on idc1 runs in PostgreSQL mode via `WIKI_USE_POSTGRES=1`
