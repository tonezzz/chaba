# Overnight System Assessment Report - 2026-08-04

## Executive Summary

**Overall Health Score:** 100/100

**Assessment Time:** 2026-08-04T04:10:04.632Z

**Total Issues Found:** 0

### ✅ System Status: Healthy

No critical or high priority issues found. System is operating normally.



## Health Check Results

| Service | Status | Response Time | Notes |
|---------|--------|---------------|-------|
| Status API | ✅ Healthy | 191ms | Status: 200 |
| Yomi API | ✅ Healthy | 7ms | Status: 200 |
| Yomi Summarization | ✅ Healthy | 42ms | Status: 200 |
| Yomi Rate Limiter | ✅ Healthy | 183ms | Status: 200 |
| Weaviate | ✅ Healthy | 8ms | Status: 200 |
| Thai Legal LLM | ✅ Healthy | 6ms | Status: 200 |
| Imagen2 | ✅ Healthy | 9ms | Status: 200 |
| GPU Queue | ✅ Healthy | 7ms | Status: 200 |

### Docker Containers

```
NAME      IMAGE     COMMAND   SERVICE   CREATED   STATUS    PORTS
```


## GPU & Queue Status

**GPU Model:** NVIDIA GeForce GTX 1650

**VRAM Usage:** 2908MB / 4096MB (71%)

**GPU Utilization:** 16%

**Temperature:** 72°C

**Active GPU Processes:**

- PID 84: PID:84 (2574MB)


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

- Total Conversations: 67
- With Summaries: 59
- Average Quality: 74%
- Daily Summaries: 163
- Conversations with Daily Summaries: 31
- Last Daily Summary Update: 2026-08-04T04:10:18.118Z
- Latest Summary Date: 2026-08-03T17:00:00.000Z


## System Resources

**Disk Usage:**
```
/dev/nvme0n1p6   98G   65G   33G  67% /
```

**Memory Usage:**
```
total        used        free      shared  buff/cache   available
Mem:            30Gi        27Gi       296Mi       1.0Gi       4.3Gi       3.1Gi
Swap:           47Gi        44Gi       3.1Gi
```

**System Load:**
```
11:10:36 up 1 day,  2:43,  2 users,  load average: 25.09, 25.14, 24.28
```


## Configuration Validation

**SSOT Configuration Files:**

- ❌ /home/tony/CascadeProjects/chaba/docs/ssot/infrastructure/ssot.health.home.yml (missing)
- ❌ /home/tony/CascadeProjects/chaba/docs/ssot/infrastructure/ssot.health.yml (missing)

**IP Addresses Found in Config:**
```
/home/tony/CascadeProjects/chaba/docs/overview/hosts.tony-dell.yml:        text: 192.168.1.42
/home/tony/CascadeProjects/chaba/docs/overview/hosts.tony-omen.yml:        text: 192.168.1.48
/home/tony/CascadeProjects/chaba/docs/overview/hosts.tony-omen.yml:      - [tony-omen, 192.168.1.48, 'Docker host']
/home/tony/CascadeProjects/chaba/docs/overview/hosts.tony-omen.yml:      - [tony-dell, 192.168.1.42, 'Secondary workstation']
/home/tony/CascadeProjects/chaba/docs/overview/hosts.tony-omen.yml:      - [VSTARCAM, 192.168.1.41, 'RTSP port 10554']
/home/tony/CascadeProjects/chaba/docs/overview/hosts.tony-omen.yml:        text: tony-omen.local resolves to a libvirt/VM network, not the Docker host; use 192.168.1.48 for services.
/home/tony/CascadeProjects/chaba/docs/overview/hostname-enforcement-strategy.md:### Files with 192.168.1.48 (26 files found)
/home/tony/CascadeProjects/chaba/docs/overview/hostname-enforcement-strategy.md:PRIMARY_IP=192.168.1.48
/home/tony/CascadeProjects/chaba/docs/overview/hostname-enforcement-strategy.md:SECONDARY_IP=192.168.1.42
/home/tony/CascadeProjects/chaba/docs/overview/hostname-enforcement-strategy.md:  echo "ERROR: Found hardcoded IP 192.168.1.48. Use tony-omen.local instead."
/home/tony/CascadeProjects/chaba/docs/overview/wireguard-architecture.md:    │   IP: 192.168.0.15           │                │   IP: 192.168.1.48           │
/home/tony/CascadeProjects/chaba/docs/overview/wireguard-architecture.md:    │   Gateway: 192.168.0.1       │                │   Gateway: 192.168.1.1       │
/home/tony/CascadeProjects/chaba/docs/overview/wireguard-architecture.md:  Mobile IP: 192.168.1.15
/home/tony/CascadeProjects/chaba/docs/overview/wireguard-architecture.md:  Home Workstation IP: 192.168.1.48
/home/tony/CascadeProjects/chaba/docs/overview/wireguard-architecture.md:  WireGuard Config: Endpoint = 192.168.1.48:51820 ✓
/home/tony/CascadeProjects/chaba/docs/overview/wireguard-architecture.md:  Mobile IP: 192.168.0.42
/home/tony/CascadeProjects/chaba/docs/overview/wireguard-architecture.md:  WireGuard Config: Endpoint = 192.168.1.48:51820 ✗ (IP no longer valid)
/home/tony/CascadeProjects/chaba/docs/overview/sessions/chaba/2026-08-03T11-45-42.yml:        text: '192.168.1.0/24 subnet with .local hostname resolution'
/home/tony/CascadeProjects/chaba/docs/overview/sessions/chaba/2026-08-03T11-45-42.yml:        text: 'tony-omen (192.168.1.48:24800)'
/home/tony/CascadeProjects/chaba/docs/overview/lab.plan-brief.yml:        text: 192.168.1.41:10554 (/tcp/av0_0) transcoded from H.265 to H.264; audio dropped.
/home/tony/CascadeProjects/chaba/docs/overview/ssot.mysystem.home.yml:        text: Primary workstation (tony-omen.local, 192.168.1.48)
/home/tony/CascadeProjects/chaba/docs/overview/ssot.mysystem.home.yml:        text: Secondary workstation (tony-dell.local, 192.168.1.42)
/home/tony/CascadeProjects/chaba/docs/overview/ssot.mysystem.home.yml:        text: 192.168.1.0/24 subnet with .local hostname resolution
/home/tony/CascadeProjects/chaba/docs/overview/ssot.mysystem.home.yml:        text: 192.168.1.48 - primary workstation
/home/tony/CascadeProjects/chaba/docs/overview/ssot.mysystem.home.yml:        text: 192.168.1.42 - secondary workstation
/home/tony/CascadeProjects/chaba/docs/overview/mdns-assessment.md:│ 192.168.1.15 │                    │ 192.168.1.48 │
/home/tony/CascadeProjects/chaba/docs/overview/mdns-assessment.md:│ local        │ ◄──mDNS response─ │ 192.168.1.48"│
/home/tony/CascadeProjects/chaba/docs/overview/mdns-assessment.md:              192.168.1.0/24 subnet
/home/tony/CascadeProjects/chaba/docs/overview/mdns-assessment.md:│ 192.168.0.15 │                    │ 192.168.1.48 │
/home/tony/CascadeProjects/chaba/docs/overview/ssot.mysystem.mobile.yml:        text: 192.168.1.0/24 subnet with .local hostname resolution

```


## Improvements Tracking

**Improvements SSOT:** ❌ Not found



## Improvement Recommendations

### Ongoing Maintenance

- Review assessment reports regularly
- Monitor GPU temperature and VRAM usage trends
- Keep Docker images and dependencies updated
- Review and clean up GPU queue failures
- Monitor disk usage growth patterns
- Track improvements in ssot.improvements.yml

---

**Assessment Duration:** 32s
**Generated by:** Automated Overnight Assessment System
**Report Location:** /home/tony/CascadeProjects/chaba/reports/overnight-assessment-2026-08-04.md
