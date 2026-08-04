# Overnight System Assessment Report - 2026-08-03

## Executive Summary

**Overall Health Score:** 100/100

**Assessment Time:** 2026-08-03T19:00:00.801Z

**Total Issues Found:** 0

### ✅ System Status: Healthy

No critical or high priority issues found. System is operating normally.



## Health Check Results

| Service | Status | Response Time | Notes |
|---------|--------|---------------|-------|
| Status API | ✅ Healthy | 41ms | Status: 200 |
| Yomi API | ✅ Healthy | 3ms | Status: 200 |
| Yomi Summarization | ✅ Healthy | 20ms | Status: 200 |
| Yomi Rate Limiter | ✅ Healthy | 42ms | Status: 200 |
| Weaviate | ✅ Healthy | 4ms | Status: 200 |
| Thai Legal LLM | ✅ Healthy | 5ms | Status: 200 |
| Imagen2 | ✅ Healthy | 5ms | Status: 200 |
| GPU Queue | ✅ Healthy | 4ms | Status: 200 |

### Docker Containers

```
NAME      IMAGE     COMMAND   SERVICE   CREATED   STATUS    PORTS
```


## GPU & Queue Status

**GPU Model:** NVIDIA GeForce GTX 1650

**VRAM Usage:** 2610MB / 4096MB (64%)

**GPU Utilization:** 100%

**Temperature:** 81°C

**Active GPU Processes:**

- PID 143: PID:143 (2466MB)


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

- Status: Unknown
- Last Run: Never
- Error Count: 0


## System Resources

**Disk Usage:**
```
/dev/nvme0n1p6   98G   62G   36G  64% /
```

**Memory Usage:**
```
total        used        free      shared  buff/cache   available
Mem:            30Gi        20Gi       2.2Gi       1.4Gi        10Gi        10Gi
Swap:           47Gi        38Gi       9.7Gi
```

**System Load:**
```
02:00:01 up 17:33,  2 users,  load average: 9.60, 13.87, 16.25
```


## Configuration Validation

**SSOT Configuration Files:**

- ✅ /home/tony/CascadeProjects/chaba/docs/overview/ssot.health.home.yml
- ✅ /home/tony/CascadeProjects/chaba/docs/overview/ssot.health.yml

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


## Improvement Recommendations

### Next Sprint Priorities

- Address: GPU temperature elevated: 81°C

### Ongoing Maintenance

- Review assessment reports regularly
- Monitor GPU temperature and VRAM usage trends
- Keep Docker images and dependencies updated
- Review and clean up GPU queue failures
- Monitor disk usage growth patterns

---

**Assessment Duration:** 1s
**Generated by:** Automated Overnight Assessment System
**Report Location:** /home/tony/CascadeProjects/chaba/reports/overnight-assessment-2026-08-03.md
