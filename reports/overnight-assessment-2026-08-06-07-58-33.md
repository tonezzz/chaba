# Overnight System Assessment Report - 2026-08-06 07-58-33

## Executive Summary

**Overall Health Score:** 100/100

**Assessment Time:** 2026-08-06T00:58:33.294Z

**Total Issues Found:** 0

### ✅ System Status: Healthy

No critical or high priority issues found. System is operating normally.



## Health Check Results

| Service | Status | Response Time | Notes |
|---------|--------|---------------|-------|
| Caddy | ✅ Healthy | 50ms | Status: 200 |
| BServer | ✅ Healthy | 8ms | Status: 200 |
| Status API | ✅ Healthy | 4ms | Status: 200 |
| Yomi API | ✅ Healthy | 2ms | Status: 200 |
| Yomi Summarization | ✅ Healthy | 8ms | Status: 200 |
| Yomi Rate Limiter | ✅ Healthy | 41ms | Status: 200 |
| Trade API | ✅ Healthy | 41ms | Container: Up 23 hours |
| Trading Terminal | ✅ Healthy | 39ms | Container: Up 36 hours |
| Redis | ✅ Healthy | 97ms | Container: Up 36 hours (healthy) |
| Postgres | ✅ Healthy | 98ms | Container: Up 36 hours (healthy) |
| Weaviate | ✅ Healthy | 11ms | Status: 200 |
| Thai Legal LLM | ✅ Healthy | 6ms | Status: 200 |
| Imagen2 | ✅ Healthy | 11ms | Status: 200 |
| Txt2Vid | ✅ Healthy | 12ms | Status: 200 |
| GPU Queue | ✅ Healthy | 11ms | Status: 200 |
| Activepieces | ✅ Healthy | 73ms | Container: Up 36 hours |
| Frigate NVR | ❌ Unhealthy | 6ms | Status: 502 |
| Camera Control | ✅ Healthy | 9ms | Status: 200 |

### Docker Containers

```
NAME      IMAGE     COMMAND   SERVICE   CREATED   STATUS    PORTS
```


## GPU & Queue Status

**GPU Model:** NVIDIA GeForce GTX 1650

**VRAM Usage:** 2944MB / 4096MB (72%)

**GPU Utilization:** 97%

**Temperature:** 77°C

**Active GPU Processes:**

- PID 71: PID:71 (2352MB)


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
- Average Quality: 46%
- Daily Summaries: 386
- Conversations with Daily Summaries: 56
- Last Daily Summary Update: 2026-08-06T00:52:47.128Z
- Latest Summary Date: 2026-08-04T17:00:00.000Z


## System Resources

**Disk Usage:**
```
/dev/nvme0n1p6   98G   70G   27G  73% /
```

**Memory Usage:**
```
total        used        free      shared  buff/cache   available
Mem:            30Gi        20Gi       4.1Gi       1.0Gi       7.5Gi        10Gi
Swap:           47Gi        39Gi       8.5Gi
```

**System Load:**
```
07:58:34 up 1 day, 13:08,  2 users,  load average: 3.03, 5.35, 8.07
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

Security scan failed: spawnSync /bin/sh ETIMEDOUT


## Improvements Tracking

**Improvements SSOT:** ✅ Found at /home/tony/CascadeProjects/chaba/docs/ssot/ssot.improvements.yml

**Improvement Status:**

- Pending: 3
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
- Medium Impact (5-7/10): 11
- Low Impact (<5/10): 0

**Medium Impact Improvements:**

- **Dependency Fields** (5/10)
- **Dependency Validation Rules** (5/10)
- **Dependency Best Practices** (5/10)
- **Impact Scoring Guide** (5/10)
- **Frigate NVR Service Failure** (5/10)
- **Docker Container Security Vulnerabilities** (5/10)
- **Assessment Enhancements** (5.5/10)
- **Performance Baselines** (5/10)
- **Immediate Actions (This Week)** (5/10)
- **Short-term Actions (Next Sprint)** (5/10)
- **Long-term Actions (Future Sprints)** (5/10)



## Improvement Recommendations

### Immediate Actions Required

- Investigate and resolve: Frigate NVR returned status 502 (expected 200)

### Next Sprint Priorities

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

**Assessment Duration:** 181s
**Generated by:** Automated Overnight Assessment System
**Report Location:** /home/tony/CascadeProjects/chaba/reports/overnight-assessment-2026-08-06-07-58-33.md
