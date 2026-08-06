---
name: health-check
description: Check health of all services defined in ssot.health.yml
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
   - File: chaba/docs/overview/ssot.health.yml
   - Parse the services list to get all monitored services

2. For each service in the configuration:
   - Extract the service type (http, container)
   - Get the appropriate check parameters (url, container name, expected status/state)
   - Perform the health check based on type:
     * For http services: curl the URL and check HTTP status code
     * For container services: check docker compose status for the container

3. Categorize results:
   - ✅ Healthy: HTTP 200-299 or container state "running"
   - ⚠️ Degraded: Slow response (>3s) or container restarting
   - ❌ Error: HTTP 4xx/5xx or container stopped/exited
   - ❓ Unknown: Timeout, connection refused, or no response

4. Generate a structured report:
   - Group by category (web, api, datastore, gpu, queue, optional)
   - Show overall health summary (total, healthy, degraded, error, unknown)
   - List each service with its status and response time
   - Highlight any services that need attention

5. If any services are unhealthy:
   - Suggest recovery actions based on the failure type
   - Reference the recovery_actions section from ssot.health.yml
   - Provide specific commands to diagnose and fix the issue

6. Exit with summary:
   - If all services healthy: "All systems operational"
   - If issues found: "X services need attention" with details
