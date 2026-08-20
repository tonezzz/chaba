---
category: operations
---

# Health Check Response

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

