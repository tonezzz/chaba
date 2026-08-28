---
category: operations
---

# Service Configuration

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

