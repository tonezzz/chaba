# idc1-db Stack

PostgreSQL database for idc1 host with official MCP PostgreSQL server for AI agent integration.

## Services

| Service | Port | Purpose |
|---------|------|---------|
| postgres | 5432 | Primary PostgreSQL database |
| mcp-postgres | - | MCP server for AI agent database access |

## Quick Start

### 1. Configure Environment

```bash
cp .env.example .env
# Edit .env with secure passwords
```

### 2. Start PostgreSQL

```bash
docker-compose up -d postgres
```

### 3. (Optional) Start MCP PostgreSQL Server

```bash
docker-compose --profile mcp up -d mcp-postgres
```

## Features

- **PostgreSQL 15** - Full-featured relational database
- **MCP Integration** - AI agents can query via Model Context Protocol
- **Persistent storage** - Data survives container restarts
- **Health checks** - Automatic container health monitoring
- **Initialization scripts** - Auto-runs SQL in `init/` folder on first start

## Access

### PostgreSQL Connection
```
Host: idc1.surf-thailand.com:5432
User: chaba (from .env)
Password: (from .env)
Database: chaba
Connection String: postgresql://chaba:password@idc1.surf-thailand.com:5432/chaba
```

### MCP Server (for AI Agents)
The MCP PostgreSQL server runs on stdio and connects to the PostgreSQL container. Use with MCP clients like Windsurf/Claude.

## Portainer Deployment (idc1)

1. **SSH to idc1**: `ssh chaba@idc1.surf-thailand.com`
2. **Ensure branch pushed**: `idc1-db` branch should be on origin
3. **In Portainer**:
   - Go to **Stacks** → **Add stack**
   - **Name**: `idc1-db`
   - **Build method**: Git repository
   - **Repository URL**: `https://github.com/tonezzz/chaba`
   - **Branch**: `idc1-db`
   - **Compose path**: `stacks/idc1-db/docker-compose.yml`
   - **Environment variables**: Paste from `.env` file
   - Click **Deploy**

## Connecting from Applications

### Python (psycopg2)
```python
import psycopg2
conn = psycopg2.connect(
    host="idc1.surf-thailand.com",
    port=5432,
    database="chaba",
    user="chaba",
    password="your_password"
)
```

### Node.js (pg)
```javascript
const { Client } = require('pg');
const client = new Client({
  host: 'idc1.surf-thailand.com',
  port: 5432,
  database: 'chaba',
  user: 'chaba',
  password: 'your_password'
});
```

## MCP PostgreSQL Server

Official Anthropic MCP server: https://github.com/modelcontextprotocol/servers/tree/main/src/postgres

### MCP Client Configuration
```json
{
  "mcpServers": {
    "postgres": {
      "command": "docker",
      "args": [
        "exec",
        "-i",
        "idc1-mcp-postgres",
        "node",
        "dist/index.js",
        "postgresql://chaba:password@postgres:5432/chaba"
      ]
    }
  }
}
```

### Available MCP Tools
- `query` - Execute SELECT statements
- `execute` - Execute INSERT/UPDATE/DELETE
- `get_tables` - List all tables
- `get_schema` - Get table schema

## Backup

```bash
# PostgreSQL dump
docker exec idc1-postgres pg_dump -U chaba chaba > backup_$(date +%Y%m%d).sql

# Restore
docker exec -i idc1-postgres psql -U chaba chaba < backup.sql
```

## Health Check

```bash
# Check container status
docker-compose ps

# View logs
docker-compose logs -f postgres
docker-compose logs -f mcp-postgres
```
