---
category: implementation
---

# Trade API Integration

## What it is

Trading data API service providing REST endpoints for dollar price data including exchange rates, dollar index, and commodity prices. Integrated with web stack via docker-compose and Caddyfile reverse proxy.
## Context/Background

Created 2026-08-04 as part of Chaba infrastructure documentation.


## Service Configuration

### Container Configuration
- **Image**: web-trade-api (built from /home/tony/CascadeProjects/trade/Dockerfile)
- **Base Image**: python:3.11-slim
- **Port**: 8000
- **Database**: PostgreSQL (postgres:5432, trade database, chaba user)
- **Dependencies**: postgres service (health check dependency)

### Docker Compose Configuration
```yaml
trade-api:
  container_name: trade-api
  build:
    context: /home/tony/CascadeProjects/trade
    dockerfile: Dockerfile
  restart: unless-stopped
  environment:
    - DB_HOST=postgres
    - DB_PORT=5432
    - DB_NAME=trade
    - DB_USER=chaba
    - DB_PASSWORD=chabapass
  networks:
    - default
  depends_on:
    postgres:
      condition: service_healthy
```

## API Endpoints

### Health Check
```bash
curl http://localhost:8000/api/health
# Response: System status, database checks, data freshness warnings
```

### Available Endpoints
- `/api/health` - System health check
- `/api/exchange_rates/{currency}` - Exchange rate data
- `/api/dollar_index` - Dollar index data
- `/api/commodity_prices/{commodity}` - Commodity price data
- `/api/available/currencies` - List available currencies
- `/api/available/commodities` - List available commodities

## Caddyfile Routing

### Current Configuration
```caddyfile
handle_path /apps/trade/api/* {
    strip_prefix /apps/trade/api
    reverse_proxy trade-api:8000
}
```

### Working Access Path
```bash
curl http://tony-omen.local:8080/apps/trade/terminal/api/trade/health
```

### Alternative Configuration (Preferred)
```caddyfile
handle_path /apps/trade/api/* {
    reverse_proxy trade-api:8000
}
```

## Database Connection

### Connection Parameters
- **Host**: postgres
- **Port**: 5432
- **Database**: trade
- **User**: chaba
- **Password**: chabapass

### Connection Verification
```bash
docker exec trade-api python -c "
import os
import psycopg2
conn = psycopg2.connect(
    host=os.environ.get('DB_HOST'),
    port=os.environ.get('DB_PORT'),
    database=os.environ.get('DB_NAME'),
    user=os.environ.get('DB_USER'),
    password=os.environ.get('DB_PASSWORD')
)
print('Database connection successful!')
conn.close()
"
```

## Health Check Response

### Sample Response
```json
{
  "status": "warning",
  "timestamp": "2026-08-04T05:57:11.603302",
  "checks": {
    "database_connection": true,
    "database_tables": true,
    "data_freshness": true,
    "data_volume": true,
    "data_quality": true,
    "system_resources": true
  },
  "issues": [],
  "warnings": [
    "exchange_rates data is 34 days old",
    "commodity_prices data is 8 days old (consider updating)",
    "High CPU usage: 94.5%",
    "High memory usage: 81.1%"
  ]
}
```

## Troubleshooting

### Container Not Starting
**Check**:
```bash
docker logs trade-api
docker ps | grep trade-api
```

### Database Connection Failed
**Verify**:
- PostgreSQL container is running and healthy
- Environment variables are correct in docker-compose.yml
- Network connectivity between containers

### API Not Accessible via Caddy
**Check**:
```bash
docker logs web
curl http://localhost:8000/api/health  # Direct container access
curl http://tony-omen.local:8080/apps/trade/api/health  # Via Caddy
```

### Caddyfile Parsing Errors
**Common Issues**:
- Duplicate matcher definitions (e.g., @raceman_noslash defined twice)
- Invalid directive syntax
- Missing closing braces

**Solution**:
```bash
docker logs web  # Check for parsing errors
# Remove duplicate matchers
# Fix syntax errors
docker exec web caddy reload --config /etc/caddy/Caddyfile
```

## Data Freshness Warnings

### Current Warnings
- Exchange rates data: 34 days old
- Commodity prices data: 8 days old

### Resolution
Update data using trade project scripts:
```bash
cd /home/tony/CascadeProjects/trade
python download_data.py
```

## Related Documentation

- **[Trade Project](/home/tony/CascadeProjects/trade/)** - Trading data API source
- **[Caddyfile Syntax Errors](caddyfile-syntax-errors.md)** - Caddyfile troubleshooting
- **[Health Check](health-check.md)** - Health check system documentation

## Tags

- **trade-api**: Trading data API service
- **docker-compose**: Container orchestration
- **caddyfile**: Reverse proxy configuration
- **postgresql**: Database integration
- **api**: REST API endpoints
- **health-check**: Service monitoring