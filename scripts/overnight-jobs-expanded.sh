#!/bin/bash
# Expanded Overnight Assessment Jobs
# Comprehensive system health and performance analysis
# Run: nohup ./scripts/overnight-jobs-expanded.sh > logs/overnight-$(date +%Y%m%d).log 2>&1 &

set -e
START_TIME=$(date +%s)
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
REPO_DIR="/home/tony/CascadeProjects/chaba"
REPORT_DIR="$REPO_DIR/reports"
LOG_DIR="$REPO_DIR/logs"
mkdir -p "$REPORT_DIR" "$LOG_DIR"

LOG_FILE="$LOG_DIR/overnight-$TIMESTAMP.log"
REPORT_FILE="$REPORT_DIR/overnight-assessment-$TIMESTAMP.md"

echo "=== Overnight Assessment Started: $(date) ===" | tee -a "$LOG_FILE"
echo "Report will be saved to: $REPORT_FILE" | tee -a "$LOG_FILE"
echo "Total Assessment Areas: 13 comprehensive areas (Enhanced with deep analysis)" | tee -a "$LOG_FILE"

# Initialize report
cat > "$REPORT_FILE" << EOF
# Overnight System Assessment Report
**Date:** $(date +%Y-%m-%d)  
**Timestamp:** $TIMESTAMP  
**Hostname:** $(hostname)  
**Duration:** Overnight run

## Executive Summary
EOF

# ============================================
# 1. HEALTH CHECK INTEGRATION (Enhanced)
# ============================================
echo "[1/14] Running Enhanced Health Check Integration..." | tee -a "$LOG_FILE"
cat >> "$REPORT_FILE" << EOF

## 1. Health Check Integration

### Service Status Summary
EOF

# Call health check API
curl -s http://tony-omen.local:8080/api/health | tee -a "$LOG_FILE" >> "$REPORT_FILE" || echo "Health check API failed" | tee -a "$LOG_FILE"

# Add service-specific health checks
cat >> "$REPORT_FILE" << EOF

### Critical Service Health
- **Caddy Web Server:** $(systemctl is-active caddy || echo "Not running")
- **PostgreSQL:** $(docker ps --filter "name=postgres" --format "{{.Status}}" || echo "Container not found")
- **Weaviate:** $(docker ps --filter "name=weaviate" --format "{{.Status}}" || echo "Container not found")
- **Redis:** $(docker ps --filter "name=redis" --format "{{.Status}}" || echo "Container not found")
- **Yomi Fetch:** $(systemctl is-active yomi-fetch.service || echo "Not running")
- **Yomi Process:** $(systemctl is-active yomi-process.service || echo "Not running")

EOF

# ============================================
# 2. COMPREHENSIVE LOG ANALYSIS (Enhanced)
# ============================================
echo "[2/13] Running Enhanced Comprehensive Log Analysis (7-day patterns)..." | tee -a "$LOG_FILE"
cat >> "$REPORT_FILE" << EOF

## 2. Enhanced Comprehensive Log Analysis

### Error Pattern Detection (7-day Analysis)
EOF

# Analyze Docker logs for errors with extended time range
echo "Analyzing Docker container logs (7-day pattern analysis)..." | tee -a "$LOG_FILE"
for container in $(docker ps --format "{{.Names}}"); do
    echo "### Container: $container" >> "$REPORT_FILE"
    
    # Extended log analysis with frequency counting
    docker logs --since 168h "$container" 2>&1 | grep -i "error\|exception\|fail" >> "$REPORT_FILE" 2>&1 || echo "No errors found in 7-day period" >> "$REPORT_FILE"
    
    # Error frequency analysis
    error_count=$(docker logs --since 168h "$container" 2>&1 | grep -ci "error\|exception\|fail" || echo "0")
    echo "**Error Frequency (7 days):** $error_count occurrences" >> "$REPORT_FILE"
    
    # Most recent errors (last 10)
    echo "**Most Recent Errors (last 10):**" >> "$REPORT_FILE"
    docker logs --tail 100 "$container" 2>&1 | grep -i "error\|exception\|fail" | tail -10 >> "$REPORT_FILE" || echo "No recent errors" >> "$REPORT_FILE"
    
    echo "" >> "$REPORT_FILE"
done

# Analyze systemd service logs with extended analysis
cat >> "$REPORT_FILE" << EOF

### Systemd Service Errors (7-day Analysis)
EOF

for service in yomi-fetch yomi-process caddy; do
    echo "### Service: $service" >> "$REPORT_FILE"
    
    # Extended time range analysis
    journalctl -u "$service" --since "7 days ago" --no-pager | grep -i "error\|exception\|fail" >> "$REPORT_FILE" 2>&1 || echo "No errors found in 7-day period" >> "$REPORT_FILE"
    
    # Error frequency
    error_count=$(journalctl -u "$service" --since "7 days ago" --no-pager | grep -ci "error\|exception\|fail" || echo "0")
    echo "**Error Frequency (7 days):** $error_count occurrences" >> "$REPORT_FILE"
    
    # Recent critical errors
    echo "**Recent Critical Errors (last 5):**" >> "$REPORT_FILE"
    journalctl -u "$service" --since "24 hours ago" --no-pager -p err -n 5 >> "$REPORT_FILE" 2>&1 || echo "No recent critical errors" >> "$REPORT_FILE"
    
    echo "" >> "$REPORT_FILE"
done

# Pattern correlation analysis
cat >> "$REPORT_FILE" << EOF

### Error Pattern Correlation Analysis
EOF

echo "Analyzing error patterns across services..." | tee -a "$LOG_FILE"

# Find common error patterns across all containers
echo "**Common Error Patterns (across all containers):**" >> "$REPORT_FILE"
docker ps --format "{{.Names}}" | while read container; do
    docker logs --since 168h "$container" 2>&1 | grep -i "error" | sort | uniq -c | sort -rn | head -5
done | sort | uniq -c | sort -rn | head -10 >> "$REPORT_FILE" 2>&1 || echo "No common patterns identified" >> "$REPORT_FILE"

echo "" >> "$REPORT_FILE"

# Service log sweep via mcp_logs (all SSOT systemd services)
echo "[2b/13] Running mcp_logs service sweep..." | tee -a "$LOG_FILE"
python3 "$REPO_DIR/scripts/overnight/service-logs-sweep.py" | tee -a "$LOG_FILE" || echo "Service log sweep failed" | tee -a "$LOG_FILE"
cat >> "$REPORT_FILE" << EOF

### Service Log Sweep (mcp_logs)
- JSON report: reports/SERVICE_ERRORS.json
- Markdown report: reports/SERVICE_ERRORS.md
- Run at: $(date)
EOF
if [ -f reports/SERVICE_ERRORS.md ]; then
    cat reports/SERVICE_ERRORS.md >> "$REPORT_FILE"
fi

# Development system assessment (produces reports/DEV_SYSTEM_ASSESSMENT.*)
python3 "$REPO_DIR/scripts/dev-system-assess.py" | tee -a "$LOG_FILE" || echo "Dev-system assessment failed" | tee -a "$LOG_FILE"
if [ -f reports/DEV_SYSTEM_ASSESSMENT.md ]; then
    cat reports/DEV_SYSTEM_ASSESSMENT.md >> "$REPORT_FILE"
fi

# Promote actionable report findings into focus-inbox drafts
python3 "$REPO_DIR/scripts/overnight/promote-reports.py" | tee -a "$LOG_FILE" || echo "Report promotion failed" | tee -a "$LOG_FILE"

# ============================================
# 2b. FOCUS STATE SWEEP
# ============================================
echo "[2b/14] Running focus-state sweep..." | tee -a "$LOG_FILE"
cat >> "$REPORT_FILE" << EOF

## 2b. Focus State Sweep

EOF
python3 "$REPO_DIR/scripts/overnight/focus-sweep.py" | tee -a "$LOG_FILE" >> "$REPORT_FILE" || echo "Focus sweep failed" | tee -a "$LOG_FILE"

echo "" >> "$REPORT_FILE"

# ============================================
# 3. DATABASE PERFORMANCE DEEP DIVE (Enhanced)
# ============================================
echo "[3/13] Running Enhanced Database Performance Deep Dive (Historical trends)..." | tee -a "$LOG_FILE"
cat >> "$REPORT_FILE" << EOF

## 3. Enhanced Database Performance Deep Dive

### PostgreSQL Performance with Historical Comparison
EOF

# Check PostgreSQL container stats with historical analysis
if docker ps | grep -q postgres; then
    cat >> "$REPORT_FILE" << EOF

#### Current Performance Metrics
EOF
    docker exec postgres psql -U chaba -c "SELECT datname, pg_size_pretty(pg_database_size(datname)) as size FROM pg_database WHERE datistemplate = false ORDER BY pg_database_size(datname) DESC;" >> "$REPORT_FILE" 2>&1 || echo "Database size query failed" >> "$REPORT_FILE"
    
    cat >> "$REPORT_FILE" << EOF

#### Connection Pool Analysis
EOF
    docker exec postgres psql -U chaba -c "SELECT state, count(*) FROM pg_stat_activity GROUP BY state ORDER BY count DESC;" >> "$REPORT_FILE" 2>&1 || echo "Connection analysis failed" >> "$REPORT_FILE"
    
    cat >> "$REPORT_FILE" << EOF

#### Long-Running Queries
EOF
    docker exec postgres psql -U chaba -c "SELECT pid, now() - pg_stat_activity.query_start as duration, query FROM pg_stat_activity WHERE (now() - pg_stat_activity.query_start) > interval '5 minutes' ORDER BY duration DESC;" >> "$REPORT_FILE" 2>&1 || echo "Long query analysis failed" >> "$REPORT_FILE"
    
    cat >> "$REPORT_FILE" << EOF

#### Database Health Trend (7-day from health checks)
EOF
    # Use PostgreSQL health data for growth analysis
    docker exec postgres psql -U chaba -c "
    SELECT 
        DATE(timestamp) as date,
        COUNT(*) as health_checks,
        COUNT(CASE WHEN status = 'healthy' THEN 1 END) as healthy_checks,
        ROUND(COUNT(CASE WHEN status = 'healthy' THEN 1 END) * 100.0 / COUNT(*), 2) as health_rate
    FROM health_checks 
    WHERE service_name = 'Postgres' AND timestamp > NOW() - INTERVAL '7 days'
    GROUP BY DATE(timestamp)
    ORDER BY date DESC;
    " >> "$REPORT_FILE" 2>&1 || echo "Growth analysis failed" >> "$REPORT_FILE"
fi

# Weaviate performance with historical analysis
cat >> "$REPORT_FILE" << EOF

### Weaviate Node Status with Historical Analysis
EOF
curl -s http://tony-omen.local:8080/api/weaviate/v1/nodes >> "$REPORT_FILE" || echo "Weaviate API failed" >> "$REPORT_FILE"

cat >> "$REPORT_FILE" << EOF

#### Weaviate Health Trend (7-day)
EOF
docker exec postgres psql -U chaba -c "
SELECT 
    DATE(timestamp) as date,
    COUNT(*) as checks,
    AVG(response_time) as avg_response_time,
    COUNT(CASE WHEN status = 'healthy' THEN 1 END) as healthy_count
FROM health_checks 
WHERE service_name = 'Weaviate' AND timestamp > NOW() - INTERVAL '7 days'
GROUP BY DATE(timestamp)
ORDER BY date DESC;
" >> "$REPORT_FILE" 2>&1 || echo "Weaviate trend analysis failed" >> "$REPORT_FILE"

# ============================================
# 4. EXTENDED GPU & QUEUE ANALYSIS (Enhanced)
# ============================================
echo "[4/14] Running Extended GPU & Queue Analysis..." | tee -a "$LOG_FILE"
cat >> "$REPORT_FILE" << EOF

## 4. Extended GPU & Queue Analysis

### GPU Status
EOF
curl -s http://tony-omen.local:8080/api/gpu/status >> "$REPORT_FILE" || echo "GPU status API failed" >> "$REPORT_FILE"

cat >> "$REPORT_FILE" << EOF

### GPU Queue Status
EOF
curl -s http://tony-omen.local:3001/api/gpu-queue/status >> "$REPORT_FILE" || echo "GPU queue API failed" >> "$REPORT_FILE"

cat >> "$REPORT_FILE" << EOF

### GPU Job History Analysis
EOF
# Analyze job patterns
curl -s http://tony-omen.local:3001/api/gpu-queue/history | tail -50 >> "$REPORT_FILE" || echo "Job history API failed" >> "$REPORT_FILE"

# ============================================
# 5. YOMI SYSTEM HEALTH (Enhanced)
# ============================================
echo "[5/14] Running Enhanced Yomi System Health..." | tee -a "$LOG_FILE"
cat >> "$REPORT_FILE" << EOF

## 5. Yomi System Health

### Yomi Health Status
EOF
curl -s http://tony-omen.local:8080/api/yomi/health >> "$REPORT_FILE" || echo "Yomi health API failed" >> "$REPORT_FILE"

cat >> "$REPORT_FILE" << EOF

### Rate Limiter Status
EOF
curl -s http://tony-omen.local:8080/api/yomi/rate-limiter-status >> "$REPORT_FILE" || echo "Rate limiter API failed" >> "$REPORT_FILE"

cat >> "$REPORT_FILE" << EOF

### Summarization Status
EOF
curl -s http://tony-omen.local:8080/api/yomi/summarization-status >> "$REPORT_FILE" || echo "Summarization API failed" >> "$REPORT_FILE"

cat >> "$REPORT_FILE" << EOF

### LINE API Rate Limit Analysis
EOF
# Analyze rate limit patterns
journalctl -u yomi-fetch --since "24 hours ago" --no-pager | grep -i "rate\|limit" | tail -20 >> "$REPORT_FILE" || echo "No rate limit logs found" >> "$REPORT_FILE"

# ============================================
# 6. NETWORK PERFORMANCE ANALYSIS (New)
# ============================================
echo "[6/14] Running Network Performance Analysis..." | tee -a "$LOG_FILE"
cat >> "$REPORT_FILE" << EOF

## 6. Network Performance Analysis

### Network Interface Statistics
EOF
ip -s link show >> "$REPORT_FILE" 2>&1

cat >> "$REPORT_FILE" << EOF

### Connectivity Checks
EOF
# Check key endpoints
for endpoint in tony-omen.local:8080 tony-omen.local:3001 tony-omen.local:11023; do
    echo "### Endpoint: $endpoint" >> "$REPORT_FILE"
    timeout 5 bash -c "echo > /dev/tcp/${endpoint/:/\/}" 2>&1 && echo "✓ Connected" || echo "✗ Failed" >> "$REPORT_FILE"
done

cat >> "$REPORT_FILE" << EOF

### DNS Resolution Performance
EOF
time host tony-omen.local >> "$REPORT_FILE" 2>&1 || echo "DNS resolution failed" >> "$REPORT_FILE"

# ============================================
# 7. BACKUP VERIFICATION (New)
# ============================================
echo "[7/14] Running Backup Verification..." | tee -a "$LOG_FILE"
cat >> "$REPORT_FILE" << EOF

## 7. Backup Verification

### Recent Backup Status
EOF

# Check for recent backups
if [ -d "/home/tony/backups" ]; then
    find /home/tony/backups -type f -mtime -1 -ls >> "$REPORT_FILE" 2>&1 || echo "No recent backups found" >> "$REPORT_FILE"
else
    echo "Backup directory not found" >> "$REPORT_FILE"
fi

cat >> "$REPORT_FILE" << EOF

### Database Backup Integrity
EOF
# Check PostgreSQL backups if they exist
if [ -d "/home/tony/backups/postgres" ]; then
    ls -lh /home/tony/backups/postgres/ | tail -10 >> "$REPORT_FILE" 2>&1 || echo "No PostgreSQL backups found" >> "$REPORT_FILE"
fi

# ============================================
# 8. CONTAINER SECURITY SCANNING (Enhanced with Trivy)
# ============================================
echo "[8/13] Running Enhanced Container Security Analysis (Trivy vulnerability scanning)..." | tee -a "$LOG_FILE"
cat >> "$REPORT_FILE" << EOF

## 8. Enhanced Container Security Analysis

### Container Image Ages
EOF
docker ps --format "{{.Image}} {{.Names}}" | while read image name; do
    echo "### $name" >> "$REPORT_FILE"
    docker images "$image" --format "{{.CreatedSince}}" >> "$REPORT_FILE" 2>&1
done

cat >> "$REPORT_FILE" << EOF

### Real Security Vulnerability Scanning (Trivy)
EOF
echo "Running Trivy security scan on running containers..." | tee -a "$LOG_FILE"

# Trivy scan for critical/high vulnerabilities
for container in $(docker ps --format "{{.Names}}"); do
    image=$(docker inspect "$container" --format='{{.Config.Image}}')
    echo "### Container: $container ($image)" >> "$REPORT_FILE"
    
    # Run Trivy scan focusing on critical/high vulnerabilities
    trivy image --severity CRITICAL,HIGH --no-progress "$image" >> "$REPORT_FILE" 2>&1 || echo "Trivy scan failed for $container" >> "$REPORT_FILE"
    
    echo "" >> "$REPORT_FILE"
done

cat >> "$REPORT_FILE" << EOF

### Security Policy Compliance
EOF
# Check for exposed ports
docker ps --format "{{.Ports}}" >> "$REPORT_FILE" 2>&1

cat >> "$REPORT_FILE" << EOF

### Container Resource Limits
EOF
docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}" >> "$REPORT_FILE" 2>&1

cat >> "$REPORT_FILE" << EOF

### Security Configuration Audit
EOF
# Check for security-sensitive configurations
echo "**Checking for security-sensitive configurations:**" >> "$REPORT_FILE"
docker ps --format "{{.Names}}" | while read container; do
    echo "### $container" >> "$REPORT_FILE"
    
    # Check for privileged mode
    if docker inspect "$container" | grep -q '"Privileged": true'; then
        echo "⚠️ WARNING: Running in privileged mode" >> "$REPORT_FILE"
    fi
    
    # Check for running as root
    if docker inspect "$container" | grep -q '"User": ""'; then
        echo "⚠️ WARNING: Running as root user" >> "$REPORT_FILE"
    fi
    
    # Check for sensitive mounts
    if docker inspect "$container" | grep -q "/var/run/docker.sock"; then
        echo "⚠️ WARNING: Docker socket mounted (security risk)" >> "$REPORT_FILE"
    fi
    
    echo "" >> "$REPORT_FILE"
done

# ============================================
# 9. DEPENDENCY SECURITY AUDIT (New)
# ============================================
echo "[9/14] Running Dependency Security Audit..." | tee -a "$LOG_FILE"
cat >> "$REPORT_FILE" << EOF

## 9. Dependency Security Audit

### Outdated Package Analysis
EOF

# Check for outdated npm packages if package.json exists
if [ -f "/home/tony/CascadeProjects/chaba/package.json" ]; then
    cd /home/tony/CascadeProjects/chaba
    npm outdated 2>&1 | head -20 >> "$REPORT_FILE" || echo "No outdated packages or npm not available" >> "$REPORT_FILE"
fi

# Check for outdated Python packages if requirements.txt exists
if [ -f "/home/tony/CascadeProjects/chaba/requirements.txt" ]; then
    pip list --outdated 2>&1 | head -20 >> "$REPORT_FILE" || echo "No outdated packages or pip not available" >> "$REPORT_FILE"
fi

cat >> "$REPORT_FILE" << EOF

### Security Vulnerability Scan
EOF
# Run basic security checks
echo "Checking for common security issues..." >> "$REPORT_FILE"
find /home/tony/CascadeProjects/chaba -name "*.env" -o -name "*secret*" -o -name "*password*" 2>/dev/null | head -10 >> "$REPORT_FILE" || echo "No obvious security files found" >> "$REPORT_FILE"

# ============================================
# 10. SYSTEM RESOURCE DEEP DIVE (Enhanced)
# ============================================
echo "[10/13] Running Enhanced System Resource Deep Dive (Capacity planning)..." | tee -a "$LOG_FILE"
cat >> "$REPORT_FILE" << EOF

## 10. Enhanced System Resource Deep Dive

### CPU Performance Analysis with Historical Comparison
EOF
# CPU frequency and governor
cat /proc/cpuinfo | grep "MHz" | head -6 >> "$REPORT_FILE" 2>&1
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor >> "$REPORT_FILE" 2>&1

cat >> "$REPORT_FILE" << EOF

#### CPU Performance Trend (7-day from health checks)
EOF
docker exec postgres psql -U chaba -c "
SELECT 
    DATE(timestamp) as date,
    AVG(response_time) as avg_response_time,
    COUNT(*) as checks,
    COUNT(CASE WHEN status = 'healthy' THEN 1 END) as healthy_count
FROM health_checks 
WHERE timestamp > NOW() - INTERVAL '7 days'
GROUP BY DATE(timestamp)
ORDER BY date DESC;
" >> "$REPORT_FILE" 2>&1 || echo "CPU trend analysis failed" >> "$REPORT_FILE"

cat >> "$REPORT_FILE" << EOF

### Memory Usage Patterns with Growth Analysis
EOF
free -h >> "$REPORT_FILE" 2>&1
vmstat 1 5 >> "$REPORT_FILE" 2>&1

cat >> "$REPORT_FILE" << EOF

#### Memory Growth Analysis (disk usage proxy)
EOF
# Track disk usage growth as memory/storage pressure indicator
df -h /home/tony/CascadeProjects/chaba >> "$REPORT_FILE" 2>&1
du -sh /home/tony/CascadeProjects/chaba/* | sort -rh | head -10 >> "$REPORT_FILE" 2>&1

cat >> "$REPORT_FILE" << EOF

### Disk I/O Performance with Trend Analysis
EOF
iostat -x 1 3 >> "$REPORT_FILE" 2>&1 || echo "iostat not available" >> "$REPORT_FILE"

cat >> "$REPORT_FILE" << EOF

### Capacity Planning Analysis
EOF
# Project disk usage growth
current_usage=$(df /home/tony/CascadeProjects/chaba | tail -1 | awk '{print $5}' | sed 's/%//')
echo "**Current Disk Usage:** $current_usage%" >> "$REPORT_FILE"

if [ "$current_usage" -gt 80 ]; then
    echo "**⚠️ WARNING:** Disk usage above 80% - capacity planning recommended" >> "$REPORT_FILE"
elif [ "$current_usage" -gt 60 ]; then
    echo "**⚠️ NOTICE:** Disk usage above 60% - monitor growth trends" >> "$REPORT_FILE"
else
    echo "**✅ OK:** Disk usage within acceptable range" >> "$REPORT_FILE"
fi

# ============================================
# 11. DOCUMENTATION CONSISTENCY (Enhanced)
# ============================================
echo "[11/14] Running Documentation Consistency Check..." | tee -a "$LOG_FILE"
cat >> "$REPORT_FILE" << EOF

## 11. Documentation Consistency

### SSOT Validation
EOF

# Run SSOT validation
cd /home/tony/CascadeProjects/chaba
if command -v devin &> /dev/null; then
    devin skill ssot-validate invoke >> "$REPORT_FILE" 2>&1 || echo "SSOT validation failed" >> "$REPORT_FILE"
else
    echo "Devin CLI not available for SSOT validation" >> "$REPORT_FILE"
fi

cat >> "$REPORT_FILE" << EOF

### Hostname Consistency Check
EOF
# Check for IP addresses that should be hostnames
grep -r "192\.168\." docs/ssot/ 2>/dev/null | head -10 >> "$REPORT_FILE" || echo "No IP addresses found in SSOT" >> "$REPORT_FILE"

# ============================================
# 12. CONFIGURATION VALIDATION (Enhanced)
# ============================================
echo "[12/14] Running Configuration Validation..." | tee -a "$LOG_FILE"
cat >> "$REPORT_FILE" << EOF

## 12. Configuration Validation

### Service Configuration Check
EOF

# Check key configuration files
for config_file in /home/tony/CascadeProjects/chaba/docs/ssot/infrastructure/ssot.health.yml; do
    if [ -f "$config_file" ]; then
        echo "### Validating: $config_file" >> "$REPORT_FILE"
        python3 -c "import yaml; yaml.safe_load(open('$config_file'))" 2>&1 && echo "✓ Valid YAML" || echo "✗ Invalid YAML" >> "$REPORT_FILE"
    fi
done

cat >> "$REPORT_FILE" << EOF

### Environment Variable Check
EOF
# Check for critical environment variables
env | grep -E "(API_KEY|DATABASE|GEMINI|OPENAI)" | head -10 >> "$REPORT_FILE" 2>&1 || echo "No critical env vars exposed" >> "$REPORT_FILE"

# ============================================
# 13. MCP HEALTH SERVER INTEGRATION (PostgreSQL)
# ============================================
echo "[13/14] Running MCP Health Server Analysis (PostgreSQL)..." | tee -a "$LOG_FILE"
cat >> "$REPORT_FILE" << EOF

## 13. MCP Health Server Analysis (PostgreSQL)

### System Health Score (7-day Analysis)
EOF

# Query PostgreSQL for historical analysis
if docker ps | grep -q postgres; then
    echo "Querying PostgreSQL for 7-day health trends..." | tee -a "$LOG_FILE"
    
    cat >> "$REPORT_FILE" << EOF

#### Recent Health Check Results (Last 50 checks)
EOF
    docker exec postgres psql -U chaba -d chaba -c "SELECT service_name, status, timestamp, response_time FROM health_checks ORDER BY timestamp DESC LIMIT 50" >> "$REPORT_FILE" 2>&1 || echo "Database query failed" >> "$REPORT_FILE"
    
    cat >> "$REPORT_FILE" << EOF

#### Service Health Summary (7-day)
EOF
    docker exec postgres psql -U chaba -d chaba -c "SELECT service_name, status, COUNT(*) as check_count, ROUND(AVG(response_time)::numeric, 2) as avg_response_time FROM health_checks WHERE timestamp > NOW() - INTERVAL '7 days' GROUP BY service_name, status ORDER BY service_name, status" >> "$REPORT_FILE" 2>&1 || echo "Summary query failed" >> "$REPORT_FILE"
    
    cat >> "$REPORT_FILE" << EOF

#### Failure Rate Analysis (7-day)
EOF
    docker exec postgres psql -U chaba -d chaba -c "SELECT service_name, COUNT(*) as total_checks, SUM(CASE WHEN status != 'healthy' THEN 1 ELSE 0 END) as failures, ROUND(SUM(CASE WHEN status != 'healthy' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as failure_rate FROM health_checks WHERE timestamp > NOW() - INTERVAL '7 days' GROUP BY service_name HAVING SUM(CASE WHEN status != 'healthy' THEN 1 ELSE 0 END) > 0 ORDER BY failure_rate DESC" >> "$REPORT_FILE" 2>&1 || echo "Failure analysis failed" >> "$REPORT_FILE"
    
    cat >> "$REPORT_FILE" << EOF

#### Recent Critical Alerts (Last 20)
EOF
    docker exec postgres psql -U chaba -d chaba -c "SELECT id, service_name, severity, message, resolved, created_at FROM alerts WHERE severity IN ('critical', 'error') ORDER BY created_at DESC LIMIT 20" >> "$REPORT_FILE" 2>&1 || echo "Alerts query failed" >> "$REPORT_FILE"
    
    cat >> "$REPORT_FILE" << EOF

#### Unresolved Alerts
EOF
    docker exec postgres psql -U chaba -d chaba -c "SELECT id, service_name, severity, message, created_at FROM alerts WHERE resolved = FALSE ORDER BY severity DESC, created_at" >> "$REPORT_FILE" 2>&1 || echo "Unresolved alerts query failed" >> "$REPORT_FILE"
    
    echo "PostgreSQL health analysis completed" | tee -a "$LOG_FILE"
else
    echo "PostgreSQL container not running" | tee -a "$LOG_FILE"
    echo "PostgreSQL not available - skipping historical analysis" >> "$REPORT_FILE"
fi

# ============================================
# 14. PERFORMANCE BASELINE COMPARISON (New)
# ============================================
echo "[14/14] Running Performance Baseline Comparison..." | tee -a "$LOG_FILE"
cat >> "$REPORT_FILE" << EOF

## 14. Performance Baseline Comparison

### Response Time Baseline Analysis (7-day)
EOF

# Compare current response times against 7-day baseline
docker exec postgres psql -U chaba -c "
WITH baseline AS (
    SELECT 
        service_name,
        AVG(response_time) as avg_baseline,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY response_time) as median_baseline,
        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY response_time) as p95_baseline
    FROM health_checks 
    WHERE timestamp > NOW() - INTERVAL '7 days' AND response_time IS NOT NULL
    GROUP BY service_name
),
current AS (
    SELECT 
        service_name,
        AVG(response_time) as avg_current,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY response_time) as median_current
    FROM health_checks 
    WHERE timestamp > NOW() - INTERVAL '1 hour' AND response_time IS NOT NULL
    GROUP BY service_name
)
SELECT 
    c.service_name,
    ROUND(b.avg_baseline::numeric, 2) as baseline_avg,
    ROUND(c.avg_current::numeric, 2) as current_avg,
    ROUND((c.avg_current - b.avg_baseline) / b.avg_baseline * 100, 2) as avg_change_percent,
    ROUND(b.median_baseline::numeric, 2) as baseline_median,
    ROUND(c.median_current::numeric, 2) as current_median,
    ROUND((c.median_current - b.median_baseline) / b.median_baseline * 100, 2) as median_change_percent
FROM current c
JOIN baseline b ON c.service_name = b.service_name
ORDER BY ABS((c.avg_current - b.avg_baseline) / b.avg_baseline) DESC;
" >> "$REPORT_FILE" 2>&1 || echo "Baseline comparison failed" >> "$REPORT_FILE"

cat >> "$REPORT_FILE" << EOF

### Health Rate Trend Analysis (7-day)
EOF

docker exec postgres psql -U chaba -c "
SELECT 
    service_name,
    COUNT(*) as total_checks,
    ROUND(AVG(CASE WHEN status = 'healthy' THEN 1.0 ELSE 0.0 END) * 100, 2) as health_rate,
    COUNT(CASE WHEN status = 'healthy' THEN 1 END) as healthy_count,
    COUNT(CASE WHEN status != 'healthy' THEN 1 END) as unhealthy_count
FROM health_checks 
WHERE timestamp > NOW() - INTERVAL '7 days'
GROUP BY service_name
ORDER BY health_rate ASC;
" >> "$REPORT_FILE" 2>&1 || echo "Health rate analysis failed" >> "$REPORT_FILE"

cat >> "$REPORT_FILE" << EOF

### Performance Degradation Detection
EOF

# Detect significant performance degradation (>20% increase in response time)
docker exec postgres psql -U chaba -c "
WITH performance_comparison AS (
    SELECT 
        h.service_name,
        AVG(h.response_time) as recent_avg,
        AVG(baseline.response_time) as baseline_avg,
        (AVG(h.response_time) - AVG(baseline.response_time)) / AVG(baseline.response_time) * 100 as performance_change
    FROM health_checks h
    JOIN (
        SELECT service_name, AVG(response_time) as response_time
        FROM health_checks 
        WHERE timestamp BETWEEN NOW() - INTERVAL '7 days' AND NOW() - INTERVAL '1 hour'
        GROUP BY service_name
    ) baseline ON h.service_name = baseline.service_name
    WHERE h.timestamp > NOW() - INTERVAL '1 hour' AND h.response_time IS NOT NULL
    GROUP BY h.service_name
)
SELECT 
    service_name,
    ROUND(recent_avg::numeric, 2) as recent_avg_ms,
    ROUND(baseline_avg::numeric, 2) as baseline_avg_ms,
    ROUND(performance_change::numeric, 2) as performance_change_percent
FROM performance_comparison
WHERE ABS(performance_change) > 20
ORDER BY performance_change DESC;
" >> "$REPORT_FILE" 2>&1 || echo "Performance degradation detection failed" >> "$REPORT_FILE"

# ============================================
# FINAL SUMMARY
# ============================================
echo "Generating Final Summary..." | tee -a "$LOG_FILE"
cat >> "$REPORT_FILE" << EOF

## Summary & Recommendations

### Health Score
- **Overall System Health:** $(systemctl is-active --all | grep -c "active") services active
- **Critical Issues:** Review error sections above
- **Performance Status:** Review resource analysis sections

### Priority Actions
1. Review any error patterns in log analysis
2. Check for services that failed health checks
3. Address any security vulnerabilities found
4. Review backup status and ensure recent backups exist
5. Check for outdated dependencies and update as needed

### Completed Assessment Areas
- ✅ Enhanced Health Check Integration
- ✅ Enhanced Comprehensive Log Analysis (7-day patterns)
- ✅ Enhanced Database Performance Deep Dive (Historical trends)
- ✅ Extended GPU & Queue Analysis
- ✅ Enhanced Yomi System Health
- ✅ Network Performance Analysis
- ✅ Backup Verification
- ✅ Enhanced Container Security Analysis (Trivy scanning)
- ✅ Dependency Security Audit
- ✅ Enhanced System Resource Deep Dive (Capacity planning)
- ✅ Documentation Consistency Check
- ✅ Configuration Validation
- ✅ MCP Health Server Integration (PostgreSQL)
- ✅ Performance Baseline Comparison (7-day trends)

**Assessment Completed:** $(date)
**Report Location:** $REPORT_FILE
**Log Location:** $LOG_FILE
EOF

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
echo "=== Overnight Assessment Completed: $(date) ===" | tee -a "$LOG_FILE"
echo "Report saved to: $REPORT_FILE" | tee -a "$LOG_FILE"
echo "Log saved to: $LOG_FILE" | tee -a "$LOG_FILE"
echo "Total runtime: $DURATION seconds" | tee -a "$LOG_FILE"

# ============================================
# AUTO-IMPROVEMENT CREATION
# ============================================
echo "Creating auto-improvement entries for critical findings..." | tee -a "$LOG_FILE"

IMPROVEMENTS_FILE="/home/tony/CascadeProjects/chaba/docs/ssot/ssot.improvements.yml"
CRITICAL_FINDINGS=()

# Function to create improvement entry
create_improvement() {
    local label="$1"
    local text="$2"
    local priority="$3"
    local category="$4"
    
    local timestamp=$(date -Iseconds)
    local entry="  - label: $label
    text: $text (Auto-generated by overnight assessment on $timestamp)
    status: pending
    priority: $priority
    effort: TBD
    category: $category
    discovered: $(date +%Y-%m-%d)
    assessment_ref: overnight-assessment-$(date +%Y%m%d)
    auto_generated: true
    git_commit: $(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    git_branch: $(git branch --show-current 2>/dev/null || echo "unknown")
    tags: ['auto-generated', '$category']"
    
    echo "$entry" >> "$IMPROVEMENTS_FILE.tmp"
    CRITICAL_FINDINGS+=("$label")
}

# Check for critical findings from assessment
# Disk usage critical
if grep -q "Disk usage critical" "$REPORT_FILE"; then
    create_improvement "Disk Usage Critical" "Disk usage critical - immediate cleanup and storage management required" "high" "storage"
fi

# Service failures
if grep -q "Container not found\|Not running\|API failed" "$REPORT_FILE"; then
    create_improvement "Service Failures Detected" "Multiple services failed health checks - investigation required" "high" "service-health"
fi

# Security vulnerabilities
if grep -q "security vulnerabilities\|HIGH\|CRITICAL" "$REPORT_FILE"; then
    create_improvement "Security Vulnerabilities Found" "Security scan found vulnerabilities requiring immediate attention" "high" "security"
fi

# Database issues
if grep -q "Database query failed\|Connection query failed" "$REPORT_FILE"; then
    create_improvement "Database Performance Issues" "Database performance issues detected - optimization required" "medium" "database"
fi

# Network connectivity issues
if grep -q "✗ Failed" "$REPORT_FILE"; then
    create_improvement "Network Connectivity Issues" "Network connectivity checks failed for critical endpoints" "medium" "network"
fi

# If we found critical issues, append to improvements file
if [ ${#CRITICAL_FINDINGS[@]} -gt 0 ]; then
    echo "Found ${#CRITICAL_FINDINGS[@]} critical findings - creating improvement entries" | tee -a "$LOG_FILE"
    
    # Find the items: array under High Priority section and append to it
    if grep -q "High Priority Improvements" "$IMPROVEMENTS_FILE"; then
        # Find the line number of "items:" under High Priority section
        items_line=$(awk '/High Priority Improvements/{found=1} found && /items:/{print NR; exit}' "$IMPROVEMENTS_FILE")
        if [ -n "$items_line" ]; then
            # Insert after the items: line
            sed -i "${items_line}r $IMPROVEMENTS_FILE.tmp" "$IMPROVEMENTS_FILE"
        else
            # Fallback: append to end
            cat "$IMPROVEMENTS_FILE.tmp" >> "$IMPROVEMENTS_FILE"
        fi
    else
        # Append to end of file
        cat "$IMPROVEMENTS_FILE.tmp" >> "$IMPROVEMENTS_FILE"
    fi
    
    rm "$IMPROVEMENTS_FILE.tmp"
    echo "Auto-improvement entries created and added to $IMPROVEMENTS_FILE" | tee -a "$LOG_FILE"
else
    echo "No critical findings requiring auto-improvement creation" | tee -a "$LOG_FILE"
    rm -f "$IMPROVEMENTS_FILE.tmp"
fi