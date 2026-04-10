# idc1-db Stack

Database services for idc1 host: PostgreSQL + Redis + optional pgAdmin.

## Services

| Service | Port | Purpose |
|---------|------|---------|
| PostgreSQL | 5432 | Primary relational database |
| Redis | 6379 | Cache, sessions, pub/sub |
| pgAdmin | 5050 | Database management UI (optional) |

## Quick Start

### 1. Configure Environment

```bash
cp .env.example .env
# Edit .env with your secure passwords
```

### 2. Start Core Services

```bash
docker-compose up -d postgres redis
```

### 3. (Optional) Start pgAdmin

```bash
docker-compose --profile admin up -d pgadmin
```

## Access

### PostgreSQL
```
Host: idc1.surf-thailand.com:5432
User: chaba (from .env)
Password: (from .env)
Database: chaba
```

### Redis
```
Host: idc1.surf-thailand.com:6379
Password: (from .env)
```

### pgAdmin (if enabled)
- URL: http://idc1.surf-thailand.com:5050
- Login: email/password from .env

## Portainer Deployment (idc1)

1. SSH to idc1: `ssh chaba@idc1.surf-thailand.com`
2. Ensure stack is on `idc1-db` branch and pushed to origin
3. In Portainer:
   - Go to **Stacks** → **Add stack**
   - Name: `idc1-db`
   - Build method: **Git repository**
   - URL: `https://github.com/tonezzz/chaba`
   - Branch: `idc1-db`
   - Compose path: `stacks/idc1-db/docker-compose.yml`
   - Environment variables: Add from .env file
   - Deploy

## Backup Strategy

PostgreSQL dumps and Redis persistence are stored in named volumes. For backup:

```bash
# PostgreSQL dump
docker exec idc1-postgres pg_dump -U chaba chaba > backup.sql

# Redis backup (if appendonly enabled)
docker exec idc1-redis redis-cli BGSAVE
```

## Health Checks

All services include healthchecks:
```bash
# Check status
docker-compose ps

# View logs
docker-compose logs -f postgres
docker-compose logs -f redis
```
