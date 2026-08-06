# Overnight System Assessment Report - 2026-08-06 13-38-37

## Executive Summary

**Overall Health Score:** 100/100

**Assessment Time:** 2026-08-06T06:38:37.696Z

**Total Issues Found:** 0

### ✅ System Status: Healthy

No critical or high priority issues found. System is operating normally.



## Health Check Results

| Service | Status | Response Time | Notes |
|---------|--------|---------------|-------|
| Caddy | ✅ Healthy | 45ms | Status: 200 |
| BServer | ✅ Healthy | 5ms | Status: 200 |
| Status API | ✅ Healthy | 6ms | Status: 200 |
| Yomi API | ✅ Healthy | 2ms | Status: 200 |
| Yomi Summarization | ✅ Healthy | 12ms | Status: 200 |
| Yomi Rate Limiter | ✅ Healthy | 59ms | Status: 200 |
| Trade API | ✅ Healthy | 52ms | Container: Up 4 hours |
| Trading Terminal | ✅ Healthy | 46ms | Container: Up 4 hours |
| Redis | ✅ Healthy | 51ms | Container: Up 4 hours (healthy) |
| Postgres | ✅ Healthy | 102ms | Container: Up 4 hours (healthy) |
| Weaviate | ✅ Healthy | 8ms | Status: 200 |
| Llama Router (Phi-3 only) | ❌ Error | 9ms | connect ECONNREFUSED 192.168.1.48:8001 |
| Imagen2 | ❌ Error | 8ms | connect ECONNREFUSED 192.168.1.48:8000 |
| Txt2Vid | ❌ Error | 4ms | connect ECONNREFUSED 192.168.1.48:8002 |
| GPU Queue | ✅ Healthy | 11ms | Status: 200 |
| Activepieces | ✅ Healthy | 99ms | Container: Up 4 hours |
| Frigate NVR | ❌ Unhealthy | 13ms | Status: 502 - Offline (2026-08-06) due to 502 errors - needs investigation |
| Camera Control | ✅ Healthy | 8ms | Status: 200 |

### Docker Containers

```
NAME      IMAGE     COMMAND   SERVICE   CREATED   STATUS    PORTS
```


## GPU & Queue Status

Failed to get GPU status: Invalid response format

**GPU Queue Status:**

- Pending: 0
- Running: 0
- Completed: 0
- Failed: 0


## Yomi System Health

**Rate Limiter Status:**

- Summary Running: 0
- Summary Queued: 0
- Daily Running: 0
- Daily Queued: 0

**Summarization Status:**

- Total Conversations: 70
- With Summaries: 40
- Average Quality: 45%
- Daily Summaries: 389
- Conversations with Daily Summaries: 55
- Last Daily Summary Update: 2026-08-06T06:08:39.250Z
- Latest Summary Date: 2026-08-04T17:00:00.000Z


## System Resources

**Disk Usage:**
```
/dev/nvme0n1p6   98G   84G   14G  87% /
```

**Memory Usage:**
```
total        used        free      shared  buff/cache   available
Mem:            30Gi        14Gi       7.1Gi       1.4Gi        10Gi        15Gi
Swap:           47Gi        16Gi        31Gi
```

**System Load:**
```
13:38:38 up 1 day, 18:49,  2 users,  load average: 6.95, 7.49, 10.00
```


## Configuration Validation

**SSOT Configuration Files:**

- ✅ /home/tony/CascadeProjects/chaba/docs/ssot/infrastructure/ssot.health.home.yml
- ✅ /home/tony/CascadeProjects/chaba/docs/ssot/infrastructure/ssot.health.yml

**IP Addresses Found in Config:**
```
/home/tony/CascadeProjects/chaba/docs/overview/hosts.tony-dell.yml:        text: 192.168.1.42
/home/tony/CascadeProjects/chaba/docs/overview/hosts.tony-omen.yml:        text: 192.168.1.48
/home/tony/CascadeProjects/chaba/docs/overview/hosts.tony-omen.yml:      - [tony-omen, 192.168.1.48, 'Docker host']
/home/tony/CascadeProjects/chaba/docs/overview/hosts.tony-omen.yml:      - [tony-dell, 192.168.1.42, 'Secondary workstation']
/home/tony/CascadeProjects/chaba/docs/overview/hosts.tony-omen.yml:      - [VSTARCAM, 192.168.1.41, 'RTSP port 10554']
/home/tony/CascadeProjects/chaba/docs/overview/hosts.tony-omen.yml:        text: "tony-omen.local resolves to 192.168.1.48 (fixed 2026-08-05: Avahi restricted to wlo1 via allow-interfaces=wlo1 in /etc/avahi/avahi-daemon.conf)."
/home/tony/CascadeProjects/chaba/docs/overview/lab.plan-brief.yml:        text: 192.168.1.41:10554 (/tcp/av0_0) transcoded from H.265 to H.264; audio dropped.

```


## Security & Dependency Status

**Security Scan Results:**

- **Total Vulnerabilities:** 55
- **Docker Vulnerabilities:** 55
- **Python Vulnerabilities:** 0
- **Node.js Vulnerabilities:** 0
- **Stale Container Images:** 0
- **Overall Status:** needs-attention

**Vulnerable Docker Images:**

- **caddy:2-alpine**: 5 vulnerabilities
- **pgvector/pgvector:pg16**: 50 vulnerabilities



## Improvements Tracking

**Improvements SSOT:** ✅ Found at /home/tony/CascadeProjects/chaba/docs/ssot/ssot.improvements.yml

**Improvement Status:**

- Pending: 4
- Planned: 4
- Completed: 9

**Dependency Validation:** ⚠️ Issues Found

- Missing dependency: "GPU Queue Priority System Enhancement" depends on non-existent "GPU Monitoring Enhancements"
- Priority inconsistency: "Security & Dependency Checking" (high) depends on lower priority "Docker Compose Configuration Fix" (low)

**Blocked Improvements:** 2

- **GPU Queue Priority System Enhancement** blocked by: GPU Monitoring Enhancements
- **Monitoring & Alerting System** blocked by: Assessment Enhancements

**Impact Analysis:**

- High Impact (≥8/10): 0
- Medium Impact (5-7/10): 12
- Low Impact (<5/10): 0

**Medium Impact Improvements:**

- **Dependency Fields** (5/10)
- **Dependency Validation Rules** (5/10)
- **Dependency Best Practices** (5/10)
- **Impact Scoring Guide** (5/10)
- **Disk Usage Critical** (5/10)
- **Frigate NVR Service Failure** (5/10)
- **Docker Container Security Vulnerabilities** (5/10)
- **Assessment Enhancements** (5.5/10)
- **Performance Baselines** (5/10)
- **Immediate Actions (This Week)** (5/10)
- **Short-term Actions (Next Sprint)** (5/10)
- **Long-term Actions (Future Sprints)** (5/10)



## Improvement Recommendations

### Immediate Actions Required

- Investigate and resolve: Llama Router (Phi-3 only) failed: connect ECONNREFUSED 192.168.1.48:8001
- Investigate and resolve: Imagen2 failed: connect ECONNREFUSED 192.168.1.48:8000
- Investigate and resolve: Txt2Vid failed: connect ECONNREFUSED 192.168.1.48:8002

### Next Sprint Priorities

- Address: GPU status endpoint returned invalid data
- Address: Disk usage elevated: 87%
- Address: Security scan found 55 vulnerabilities
- Address: Critical dependency issues found: 1

### Ongoing Maintenance

- Review assessment reports regularly
- Monitor GPU temperature and VRAM usage trends
- Keep Docker images and dependencies updated
- Review and clean up GPU queue failures
- Monitor disk usage growth patterns
- Track improvements in ssot.improvements.yml
- Review security scan results and patch vulnerabilities
- Monitor container image ages and update stale images

---

**Assessment Duration:** 59s
**Generated by:** Automated Overnight Assessment System
**Report Location:** /home/tony/CascadeProjects/chaba/reports/overnight-assessment-2026-08-06-13-38-37.md
