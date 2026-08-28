---
category: operations
---

# Assessment Areas

### 1. Health Check Integration
- Calls existing health check API: `http://tony-omen.local:8080/api/health`
- Checks all service categories: web, api, datastore, gpu, queue, optional
- Tests individual service endpoints with response time measurement
- Identifies failed services and suggests recovery actions

### 2. GPU & Queue Analysis
- GPU status: model, VRAM usage, utilization, temperature
- GPU queue status: pending, running, completed, failed jobs
- Active GPU processes with memory usage
- Temperature and VRAM threshold monitoring

### 3. Yomi System Health
- Yomi API health status
- Rate limiter statistics (running/queued jobs)
- Circuit breaker states and failure patterns
- Summarization service status and error counts

### 4. Database & Cache Performance
- Docker container status checks
- Postgres, Redis, Weaviate service availability
- Connection pool performance monitoring

### 5. System Resources
- Disk usage analysis with threshold alerts
- Memory usage and swap utilization
- System load average monitoring

### 6. Configuration Validation
- SSOT YAML file existence checks
- Hostname enforcement validation (.local vs IP addresses)
- Configuration consistency verification

### 7. Improvements Tracking
- Checks for `ssot.improvements.yml` file existence
- Monitors pending, planned, and completed improvement counts
- Alerts if pending improvements exceed threshold (>5)
- Links improvement tracking to assessment reports

