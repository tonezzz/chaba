---
name: health-check
description: Check health of all services defined in ssot.health.yml with auto network detection
allowed-tools:
  - read
  - exec
  - grep
triggers:
  - user
  - model
---

Check health of all services defined in SSOT health configuration:

1. Read the SSOT health configuration file:
   - File: chaba/docs/ssot/infrastructure/ssot.health.yml
   - Parse profiles section for network configuration
   - Parse services list to get all monitored services

2. Auto-detect network profile:
   - Check if tony-omen.local resolves successfully → use home profile
   - If tony-omen.local fails → use mobile profile with IP detection
   - Get current IP for mobile profile: ip route get 1.1.1.1 | awk '{print $7}'
   - Replace {profile} placeholder with appropriate base URL

3. For each service in the configuration:
   - Check if service has profiles field and matches current profile
   - Extract the service type (http, container, systemd)
   - Get the appropriate check parameters (url, container name, service name, expected status/state)
   - Replace {profile} placeholder in URLs with detected base URL
   - Perform the health check based on type:
     * For http services: curl the URL and check HTTP status code
     * For container services: check docker compose status for the container
     * For systemd services: check systemctl --user status for the service

4. Categorize results:
   - ✅ Healthy: HTTP 200-299, container state "running", or systemd state "active"
   - ⚠️ Degraded: Slow response (>3s) or container restarting
   - ❌ Error: HTTP 4xx/5xx, container stopped/exited, or systemd inactive
   - ❓ Unknown: Timeout, connection refused, or no response

5. Generate a structured report:
   - Show detected network profile and base URL
   - Group by category (web, api, datastore, gpu, queue, optional, system)
   - Show overall health summary (total, healthy, degraded, error, unknown)
   - List each service with its status and response time
   - Highlight any services that need attention
   - Show dependency status if dependencies are defined

6. If any services are unhealthy:
   - Suggest recovery actions based on the failure type
   - Reference the recovery_actions section from ssot.health.yml
   - Provide specific commands to diagnose and fix the issue
   - Check if dependencies are also failing

7. Exit with summary:
   - If all services healthy: "All systems operational"
   - If issues found: "X services need attention" with details
