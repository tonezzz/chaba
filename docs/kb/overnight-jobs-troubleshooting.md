---
category: operations
---

# Troubleshooting

### Script Fails to Start
```bash
# Check script permissions
ls -l scripts/overnight-jobs-expanded.sh

# Ensure it's executable
chmod +x scripts/overnight-jobs-expanded.sh

# Test syntax
bash -n scripts/overnight-jobs-expanded.sh
```

### API Endpoints Unavailable
The script will continue running even if individual APIs fail. Check the log for specific API failures:
```bash
grep "API failed" logs/overnight-manual-TIMESTAMP.log
```

### Missing Dependencies
The script uses standard Linux tools. If something is missing:
```bash
# Check for required tools
which curl docker journalctl ip host

# Install missing tools on Ubuntu/Debian
sudo apt-get install curl iproute2 iputils-ping sysstat
```

### MCP Health Server Integration
The MCP Health Server integration (Area 13) uses PostgreSQL for historical analysis:
```bash
# Check if PostgreSQL container is running
docker ps | grep postgres

# If not running, the script will skip historical analysis with a graceful fallback
# PostgreSQL should be running as part of the Chaba infrastructure
```

**PostgreSQL Integration:**
- Direct PostgreSQL queries to chaba database (health_checks, alerts tables)
- Provides 7-day health trends, failure rates, and alert analysis
- No MCP client dependency required
- Graceful fallback if PostgreSQL container unavailable
- Unified database architecture with application data

### Systemd Timer Issues
```bash
# Check timer status
sudo systemctl status overnight-assessment.timer

# View timer logs
sudo journalctl -u overnight-assessment.timer

# Manually trigger the timer
sudo systemctl start overnight-assessment.service
```

