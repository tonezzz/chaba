# Improvements Triage Report — 2026-08-18

Triage of the 8 pending high/medium/low improvements against the overnight assessment report
`reports/overnight-assessment-20260818-020000.md` and live state.

## Summary Table

| Improvement | Evidence | Status | Notes |
|---|---|---|---|
| Service Failures Detected | Critical Service Health lists Caddy inactive, Yomi Fetch/Process inactive, PostgreSQL/Weaviate/Redis blank. Live: Caddy recovered (200), Yomi services still `inactive`, Redis missing. | in_progress | Caddy recovered; Redis and Yomi still need fixing. |
| Security Vulnerabilities Found | Trivy section 8 and dependency audit section 9 show HIGH/CRITICAL vulnerabilities across imagen2-inference, status-api, ollama, web, gemini-ollama-proxy, gpu-queue-processor, gpu-queue. | in_progress | Actionable; needs patching/image updates. |
| Network Connectivity Issues | `tony-omen.local:8080/:3001/:11023` failed in report. Live `tony-omen:8080` works; `.local` failure is mDNS/Avahi noise; `:3001` returns 404; `:11023` (MDDB) is service-specific. | accepted | Transient `.local` resolution/connectivity noise. |
| Docker Container Security Vulnerabilities | 2026-08-18 Trivy supersedes the prior "5 vulnerabilities"; many HIGH/CRITICAL across all scanned containers (imagen2-inference 365/21, status-api 46/17, etc.). | in_progress | Keep as the container patching task. |
| Redis Container Down | Report has empty Redis line; `docker ps`/`docker ps -a` show no running redis container. | in_progress | Confirmed missing. |
| Raceman PHP Container Down | `docker ps`/`docker ps -a` on tony-omen show no raceman-php container. | in_progress | Confirmed missing. |
| SSOT file optimization | Not raised in the 2026-08-18 overnight report; pre-existing planned task. | pending | Keep pending until active focus. |
| SSOT and docs currency check after changes | Not raised in the 2026-08-18 overnight report; pre-existing process improvement. | pending | Keep pending for future tooling. |

## Live Verification Performed

- `curl -s http://tony-omen.local:8080/api/health` → failed
- `curl -s http://tony-omen:8080/api/health` → 200 `{"status":"ok"}`
- `curl -s http://tony-omen:3001/` → 404
- `curl -s http://tony-omen:11023/health` → failed
- `docker ps` / `docker ps -a` → web, sensor-reader, gemini-ollama-proxy, gpu-queue-processor, gpu-queue, ollama, imagen2-inference; no redis or raceman-php
- `systemctl --user is-active yomi-fetch yomi-process` → `inactive` for both

## Decisions

- 5 items moved to `in_progress` (Service Failures, Security Vulns, Docker Vulns, Redis, Raceman).
- 1 item `accepted` as transient/noise (Network Connectivity).
- 2 planned improvements remain `pending` (SSOT file optimization, currency check).
