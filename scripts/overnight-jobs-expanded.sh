#!/bin/bash
# Expanded Overnight Assessment Jobs
# Comprehensive system health and performance analysis
# Run: nohup ./scripts/overnight-jobs-expanded.sh > logs/overnight-$(date +%Y%m%d).log 2>&1 &

set -e
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="/home/tony/CascadeProjects/chaba/reports"
LOG_DIR="/home/tony/CascadeProjects/chaba/logs"
mkdir -p "$REPORT_DIR" "$LOG_DIR"

LOG_FILE="$LOG_DIR/overnight-$TIMESTAMP.log"
REPORT_FILE="$REPORT_DIR/overnight-assessment-$TIMESTAMP.md"

echo "=== Overnight Assessment Started: $(date) ===" | tee -a "$LOG_FILE"
echo "Report will be saved to: $REPORT_FILE" | tee -a "$LOG_FILE"

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
echo "[1/12] Running Enhanced Health Check Integration..." | tee -a "$LOG_FILE"
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
# 2. COMPREHENSIVE LOG ANALYSIS (New)
# ============================================
echo "[2/12] Running Comprehensive Log Analysis..." | tee -a "$LOG_FILE"
cat >> "$REPORT_FILE" << EOF

## 2. Comprehensive Log Analysis

### Error Pattern Detection
EOF

# Analyze Docker logs for errors
echo "Analyzing Docker container logs..." | tee -a "$LOG_FILE"
for container in $(docker ps --format "{{.Names}}"); do
    echo "### Container: $container" >> "$REPORT_FILE"
    docker logs --tail 500 "$container" 2>&1 | grep -i "error\|exception\|fail" | tail -20 >> "$REPORT_FILE" || echo "No errors found" >> "$REPORT_FILE"
    echo "" >> "$REPORT_FILE"
done

# Analyze systemd service logs
cat >> "$REPORT_FILE" << EOF

### Systemd Service Errors
EOF

for service in yomi-fetch yomi-process caddy; do
    echo "### Service: $service" >> "$REPORT_FILE"
    journalctl -u "$service" --since "24 hours ago" --no-pager | grep -i "error\|exception\|fail" | tail -10 >> "$REPORT_FILE" || echo "No errors found" >> "$REPORT_FILE"
    echo "" >> "$REPORT_FILE"
done

# ============================================
# 3. DATABASE PERFORMANCE DEEP DIVE (New)
# ============================================
echo "[3/12] Running Database Performance Deep Dive..." | tee -a "$LOG_FILE"
cat >> "$REPORT_FILE" << EOF

## 3. Database Performance Deep Dive

### PostgreSQL Performance
EOF

# Check PostgreSQL container stats
if docker ps | grep -q postgres; then
    docker exec postgres pg_stat_statements | head -20 >> "$REPORT_FILE" 2>&1 || echo "pg_stat_statements not available" >> "$REPORT_FILE"
    
    cat >> "$REPORT_FILE" << EOF

### Database Size and Growth
EOF
    docker exec postgres psql -U postgres -c "\l+" >> "$REPORT_FILE" 2>&1 || echo "Database query failed" >> "$REPORT_FILE"
    
    cat >> "$REPORT_FILE" << EOF

### Connection Pool Status
EOF
    docker exec postgres psql -U postgres -c "SELECT count(*) FROM pg_stat_activity;" >> "$REPORT_FILE" 2>&1 || echo "Connection query failed" >> "$REPORT_FILE"
fi

# Weaviate performance
cat >> "$REPORT_FILE" << EOF

### Weaviate Node Status
EOF
curl -s http://tony-omen.local:8080/api/weaviate/v1/nodes >> "$REPORT_FILE" || echo "Weaviate API failed" >> "$REPORT_FILE"

# ============================================
# 4. EXTENDED GPU & QUEUE ANALYSIS (Enhanced)
# ============================================
echo "[4/12] Running Extended GPU & Queue Analysis..." | tee -a "$LOG_FILE"
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
echo "[5/12] Running Enhanced Yomi System Health..." | tee -a "$LOG_FILE"
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
echo "[6/12] Running Network Performance Analysis..." | tee -a "$LOG_FILE"
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
echo "[7/12] Running Backup Verification..." | tee -a "$LOG_FILE"
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
# 8. CONTAINER SECURITY SCANNING (New)
# ============================================
echo "[8/12] Running Container Security Analysis..." | tee -a "$LOG_FILE"
cat >> "$REPORT_FILE" << EOF

## 8. Container Security Analysis

### Container Image Ages
EOF
docker ps --format "{{.Image}} {{.Names}}" | while read image name; do
    echo "### $name" >> "$REPORT_FILE"
    docker images "$image" --format "{{.CreatedSince}}" >> "$REPORT_FILE" 2>&1
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

# ============================================
# 9. DEPENDENCY SECURITY AUDIT (New)
# ============================================
echo "[9/12] Running Dependency Security Audit..." | tee -a "$LOG_FILE"
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
# 10. SYSTEM RESOURCE DEEP DIVE (New)
# ============================================
echo "[10/12] Running System Resource Deep Dive..." | tee -a "$LOG_FILE"
cat >> "$REPORT_FILE" << EOF

## 10. System Resource Deep Dive

### CPU Performance Analysis
EOF
# CPU frequency and governor
cat /proc/cpuinfo | grep "MHz" | head -6 >> "$REPORT_FILE" 2>&1
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor >> "$REPORT_FILE" 2>&1

cat >> "$REPORT_FILE" << EOF

### Memory Usage Patterns
EOF
free -h >> "$REPORT_FILE" 2>&1
vmstat 1 5 >> "$REPORT_FILE" 2>&1

cat >> "$REPORT_FILE" << EOF

### Disk I/O Performance
EOF
iostat -x 1 3 >> "$REPORT_FILE" 2>&1 || echo "iostat not available" >> "$REPORT_FILE"

cat >> "$REPORT_FILE" << EOF

### Disk Space Analysis
EOF
df -h >> "$REPORT_FILE" 2>&1
du -sh /home/tony/CascadeProjects/chaba/* | sort -rh | head -10 >> "$REPORT_FILE" 2>&1

# ============================================
# 11. DOCUMENTATION CONSISTENCY (Enhanced)
# ============================================
echo "[11/12] Running Documentation Consistency Check..." | tee -a "$LOG_FILE"
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
echo "[12/12] Running Configuration Validation..." | tee -a "$LOG_FILE"
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
- ✅ Comprehensive Log Analysis
- ✅ Database Performance Deep Dive
- ✅ Extended GPU & Queue Analysis
- ✅ Enhanced Yomi System Health
- ✅ Network Performance Analysis
- ✅ Backup Verification
- ✅ Container Security Analysis
- ✅ Dependency Security Audit
- ✅ System Resource Deep Dive
- ✅ Documentation Consistency Check
- ✅ Configuration Validation

**Assessment Completed:** $(date)
**Report Location:** $REPORT_FILE
**Log Location:** $LOG_FILE
EOF

echo "=== Overnight Assessment Completed: $(date) ===" | tee -a "$LOG_FILE"
echo "Report saved to: $REPORT_FILE" | tee -a "$LOG_FILE"
echo "Log saved to: $LOG_FILE" | tee -a "$LOG_FILE"