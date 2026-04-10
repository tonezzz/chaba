# idc1-db Stack

Lightweight SQLite database for idc1 host with web-based management interface.

## Services

| Service | Port | Purpose |
|---------|------|---------|
| sqlite-web | 8080 | SQLite database with web UI |

## Quick Start

### 1. Start the Service

```bash
docker-compose up -d sqlite-web
```

### 2. Access Web UI

Open http://idc1.surf-thailand.com:8080 in your browser.

## Features

- **Web-based SQLite browser** - Create tables, run queries, export data
- **Persistent storage** - Database survives container restarts
- **Zero configuration** - SQLite is serverless, no credentials needed
- **Lightweight** - Perfect for small to medium applications

## Database Location

- **Container path**: `/data/chaba.db`
- **Docker volume**: `idc1-db_sqlite-data`
- **Host backup path**: `/var/lib/docker/volumes/idc1-db_sqlite-data/_data/chaba.db`

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
   - Click **Deploy**

## Connecting from Applications

### Python
```python
import sqlite3
conn = sqlite3.connect('/data/chaba.db')  # Same container/volume
```

### Node.js (better-sqlite3)
```javascript
const Database = require('better-sqlite3');
const db = new Database('/data/chaba.db');
```

## Backup

```bash
# Backup the SQLite file directly
docker exec idc1-sqlite-web cat /data/chaba.db > backup_$(date +%Y%m%d).db

# Or copy from volume
cp /var/lib/docker/volumes/idc1-db_sqlite-data/_data/chaba.db backup.db
```

## Health Check

```bash
# Check container status
docker-compose ps

# View logs
docker-compose logs -f sqlite-web
```
