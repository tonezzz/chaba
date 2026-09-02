# MDDB Monitoring and Backup Configuration

## Health Check Integration

**Add to**: `/home/tony/CascadeProjects/chaba-kbman/docs/ssot/infrastructure/ssot.health.home.yml`

```yaml
mddb:
  service: mddb container
  health_check:
    type: http
    url: http://mddb:11023/health
    interval: 30s
    timeout: 10s
    retries: 3
  metrics:
    - container_status
    - volume_usage
    - api_response_time
    - mcp_tool_availability
    - search_performance
  alerts:
    - container_down
    - high_volume_usage
    - api_failure
    - mcp_unavailable
```

## Backup Strategy

### 1. Volume Backup
**Add to existing backup script** (`/home/tony/CascadeProjects/chaba-kbman/scripts/backup.sh`):

```bash
# Backup MDDB data volume
backup_mddb() {
    echo "Backing up MDDB data volume..."
    docker run --rm \
      -v mddb-data:/data \
      -v /backup:/backup \
      alpine tar czf /backup/mddb-$(date +%Y%m%d-%H%M%S).tar.gz -C /data .
    echo "MDDB backup completed"
}

# Add to main backup function
backup_mddb
```

### 2. Automated Backup Schedule
**Add to crontab**:
```bash
# Daily MDDB backup at 2 AM
0 2 * * * /home/tony/CascadeProjects/chaba-kbman/stacks/web/mddb/backup.sh

# Weekly full backup on Sunday at 3 AM
0 3 * * 0 /home/tony/CascadeProjects/chaba-kbman/stacks/web/mddb/backup.sh
```

## Monitoring Integration

### 1. Netdata Integration
**Add to existing Netdata configuration**:

```yaml
# MDDB container monitoring
mddb_container:
  name: mddb
  metrics:
    - cpu_usage
    - memory_usage
    - network_io
    - disk_io
    - volume_usage
```

### 2. Status API Integration
**Add to existing status-api** (`/home/tony/CascadeProjects/chaba/stacks/web/status-api/main.py`):

```python
# Add MDDB health check
def check_mddb():
    try:
        response = requests.get('http://mddb:11023/health', timeout=5)
        mcp_tools = requests.get('http://mddb:9000/tools', timeout=5)
        return {
            'status': 'healthy' if response.status_code == 200 else 'unhealthy',
            'response_time': response.elapsed.total_seconds(),
            'mcp_tools_available': len(mcp_tools.json()) if mcp_tools.status_code == 200 else 0,
            'expected_mcp_tools': 77
        }
    except Exception as e:
        return {'status': 'error', 'error': str(e)}
```

## Log Management

**Configure logging in docker-compose.yml**:

```yaml
services:
  mddb:
    # ... existing config
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

## Alert Configuration

**Set up alerts for**:
- Container downtime (>5 minutes)
- Volume usage >80%
- API response time >2s
- MCP tool count <77
- Search performance degradation
- Backup failures

## Performance Monitoring

### Key Metrics to Monitor
1. **Container Health**
   - CPU usage
   - Memory usage
   - Disk I/O
   - Network I/O

2. **API Performance**
   - HTTP response time
   - gRPC response time
   - Error rates
   - Request throughput

3. **MCP Performance**
   - Tool availability (should be 77)
   - Tool execution time
   - MCP connection stability

4. **Search Performance**
   - Search response times by algorithm
   - Index size and growth
   - Search result relevance

5. **Storage**
   - Volume usage trends
   - Index size
   - Backup sizes

## Troubleshooting Guide

### Common Issues

1. **Container Not Starting**
   ```bash
   docker logs mddb
   docker inspect mddb
   ```

2. **MCP Tools Not Available**
   ```bash
   curl http://localhost:9000/tools
   docker exec mddb curl http://localhost:9000/tools
   ```

3. **Search Performance Issues**
   - Check search algorithm configuration
   - Monitor index size
   - Review resource allocation

4. **Backup Failures**
   - Check volume permissions
   - Verify disk space
   - Review backup logs

## Maintenance Tasks

### Daily
- Review health check status
- Check backup completion
- Monitor resource usage

### Weekly
- Review performance metrics
- Check log files for errors
- Verify backup integrity

### Monthly
- Review storage growth trends
- Test restore procedure
- Update documentation if needed
- Review and optimize search algorithms