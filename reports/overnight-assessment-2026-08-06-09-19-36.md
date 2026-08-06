# Overnight System Assessment Report - 2026-08-06 09-19-36

## Executive Summary

**Overall Health Score:** 100/100

**Assessment Time:** 2026-08-06T02:19:36.620Z

**Total Issues Found:** 0

### ✅ System Status: Healthy

No critical or high priority issues found. System is operating normally.



## Health Check Results

| Service | Status | Response Time | Notes |
|---------|--------|---------------|-------|
| Caddy | ✅ Healthy | 130ms | Status: 200 |
| BServer | ✅ Healthy | 5ms | Status: 200 |
| Status API | ✅ Healthy | 5ms | Status: 200 |
| Yomi API | ✅ Healthy | 2ms | Status: 200 |
| Yomi Summarization | ✅ Healthy | 7ms | Status: 200 |
| Yomi Rate Limiter | ✅ Healthy | 40ms | Status: 200 |
| Trade API | ✅ Healthy | 44ms | Container: Up 24 hours |
| Trading Terminal | ✅ Healthy | 41ms | Container: Up 37 hours |
| Redis | ✅ Healthy | 48ms | Container: Up 37 hours (healthy) |
| Postgres | ✅ Healthy | 49ms | Container: Up 37 hours (healthy) |
| Weaviate | ✅ Healthy | 4ms | Status: 200 |
| Llama Router (Phi-3 only) | ✅ Healthy | 4ms | Status: 200 - Thai legal model offline (2026-08-06) due to GPU memory constraints |
| Imagen2 | ✅ Healthy | 12ms | Status: 200 - Offline (2026-08-06) due to GPU memory constraints |
| Txt2Vid | ✅ Healthy | 8ms | Status: 200 - Offline (2026-08-06) due to GPU memory constraints |
| GPU Queue | ✅ Healthy | 8ms | Status: 200 |
| Activepieces | ✅ Healthy | 111ms | Container: Up 37 hours |
| Frigate NVR | ❌ Unhealthy | 5ms | Status: 502 - Offline (2026-08-06) due to 502 errors - needs investigation |
| Camera Control | ✅ Healthy | 11ms | Status: 200 |

### Docker Containers

```
NAME      IMAGE     COMMAND   SERVICE   CREATED   STATUS    PORTS
```


## GPU & Queue Status

**GPU Model:** NVIDIA GeForce GTX 1650

**VRAM Usage:** 2716MB / 4096MB (66%)

**GPU Utilization:** 96%

**Temperature:** 80°C

**Active GPU Processes:**

- PID 103: PID:103 (2124MB)


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
- With Summaries: 39
- Average Quality: 44%
- Daily Summaries: 380
- Conversations with Daily Summaries: 56
- Last Daily Summary Update: 2026-08-06T02:15:33.967Z
- Latest Summary Date: 2026-08-04T17:00:00.000Z


## System Resources

**Disk Usage:**
```
/dev/nvme0n1p6   98G   84G   14G  86% /
```

**Memory Usage:**
```
total        used        free      shared  buff/cache   available
Mem:            30Gi        20Gi       1.4Gi       1.1Gi        10Gi       9.7Gi
Swap:           47Gi        39Gi       8.2Gi
```

**System Load:**
```
09:19:37 up 1 day, 14:30,  2 users,  load average: 23.60, 19.08, 19.27
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

### Next Sprint Priorities

- Address: Disk usage elevated: 86%
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

**Assessment Duration:** 182s
**Generated by:** Automated Overnight Assessment System
**Report Location:** /home/tony/CascadeProjects/chaba/reports/overnight-assessment-2026-08-06-09-19-36.md
