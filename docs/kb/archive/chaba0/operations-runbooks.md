---
kind: archive-report
bank: chaba-archive
source_repo: chaba0
source_commit: b5f1a6268e3e754a3281c55261a4ba7c8980bae9
topic: operations-runbooks
status: historical
period: [2025-12, 2026-03]
follows: []
superseded_by: current SSOT + health-check scripts
covers:
  - README.md
  - TODO.md
  - docs/README.md
  - docs/backlog.md
  - docs/dev-host.md
  - docs/docker-management.md
  - docs/pc1-runbook.md
  - experiments/README.md
  - scripts/ai-app-fast.ps1
  - scripts/apply-host-caddy-deka.ps1
  - scripts/build-ui.sh
  - scripts/deploy-a1-idc1.sh
  - scripts/deploy-branch.ps1
  - scripts/deploy-dev-host-mirror.sh
  - scripts/deploy-idc1-test.sh
  - scripts/deploy-node-1.sh
  - scripts/deploy-tony-site.sh
  - scripts/dever-deploy-git-branch.ps1
  - scripts/diagnostics-a1-idc1.sh
  - scripts/extract-secrets-and-endpoints.ps1
  - scripts/idc1-caddy-ensure-hub.sh
  - scripts/idc1-caddy-probe.sh
  - scripts/idc1-caddy-reload.sh
  - scripts/idc1-code-server-logs.sh
  - scripts/idc1-code-server-proxy-status.sh
  - scripts/idc1-code-server-proxy-switch-to-stack.sh
  - scripts/idc1-code-server-restart.sh
  - scripts/idc1-code-server-status.sh
  - scripts/idc1-code-server.sh
  - scripts/idc1-docker-ps.sh
  - scripts/idc1-fix-mcp0-vpn.sh
  - scripts/idc1-health-sweep.sh
  - scripts/idc1-log-bundle.sh
  - scripts/idc1-ls-workspace.sh
  - scripts/idc1-stack-deploy-via-1mcp.ps1
  - scripts/idc1-stack-verify.ps1
  - scripts/idc1-stack.ps1
  - scripts/migrate-idc1-stacks.ps1
  - scripts/monitor-idc1-stack.ps1
  - scripts/pc1-ai.ps1
  - scripts/pc1-caddy-logs.ps1
  - scripts/pc1-caddy-reload.ps1
  - scripts/pc1-caddy-restart.ps1
  - scripts/pc1-caddy-status.ps1
  - scripts/pc1-db.ps1
  - scripts/pc1-deka.ps1
  - scripts/pc1-devops.ps1
  - scripts/pc1-gpu.ps1
  - scripts/pc1-mcp-smoke-test.ps1
  - scripts/pc1-stack-self.sh
  - scripts/pc1-stack.ps1
  - scripts/pc1-start-all-stacks.ps1
  - scripts/pc1-stop-all-stacks.ps1
  - scripts/pc1-sync-prefixed-env.ps1
  - scripts/pc1-web.ps1
  - scripts/pc2-ai.ps1
  - scripts/pc2-devops.ps1
  - scripts/pc2-kvm-probe.sh
  - scripts/pc2-stack.ps1
  - scripts/pc2-start-all-stacks.ps1
  - scripts/pc2-stop-all-stacks.ps1
  - scripts/pc2-sync-prefixed-env.ps1
  - scripts/pc2-webtops.ps1
  - scripts/pc2-worker/deploy.ps1
  - scripts/pc2-worker/pc2-stack.ps1
  - scripts/pc2-worker/smoke-test.ps1
  - scripts/pc2-worker/start.ps1
  - scripts/pc2-worker/stop.ps1
  - scripts/pc2-worker/sync-env.ps1
  - scripts/pc2-worker-deploy-via-1mcp.ps1
  - scripts/preview-detects.ps1
  - scripts/preview-test.ps1
  - scripts/preview-vaja.ps1
  - scripts/pull-node-1.sh
  - scripts/push_chat1_via_api.py
  - scripts/register-mcp-provider.ps1
  - scripts/release-a1-idc1.ps1
  - scripts/reorganize-stacks.ps1
  - scripts/rollback-a1-idc1.sh
  - scripts/rollback-node-1.sh
  - ... (26 more files under topic)
extracted: 2026-09-24
extracted_by: gemini-2.5-flash (benchmark)
---

# Operations Runbooks — archive of chaba0

## Summary
This topic details the operational runbooks and infrastructure management practices for the `chaba0` platform. It covers the designated sources of truth for infrastructure configuration, local development overrides, and the CI/CD deployment policies. Key aspects include the modularization of Docker Compose stacks for PC1 and IDC1 environments, the use of `mcp-docker` for API-driven container management, and a suite of scripts for stack lifecycle management and diagnostics.

## Timeline
dates unknown — frozen 2026-03-28

## Still-true facts
*   Operational truth for `chaba0` lived in `docs/stacks.md` and per-stack JSON docs. [historical]
*   `pc1-stack` supported local environment overrides via `PC1_STACK_ENV_FILE` pointing to a gitignored `.env.local` file. [still-true]
*   The preferred CI/CD workflow involved GitHub Pull Requests targeting `main`. [still-true]
*   Deployment from `C:\chaba` was the policy for Windows hosts, serving as the single "deploy working copy" with host secret materialization. [superseded-by chaba/ada-pi's current deploy policy]
*   `mcp-docker` was the default HTTP wrapper interface for managing Docker containers and Compose stacks, discoverable by `mcp0`. [still-true]
*   The `dev-host` environment replaced the `node-1` container as the canonical development target, mirroring production nodes and exposing convenience routes. [superseded-by chaba/ada-pi's current dev environment]
*   PC1 Docker Compose stacks were split into modular units: `pc1-db`, `pc1-gpu`, `pc1-ai`, `pc1-devops`, `pc1-web`, `pc1-stack`, `pc1-deka`. [historical]
*   A recommended start order for PC1 stacks was based on dependencies. [historical]
*   `dev-host` provided aggregated `/api/health` checks for downstream proxies. [still-true]
*   `idc1` no longer used `mcp0` for VPN DNS + Caddy config sync. [historical]

## Key details
*   **Operational Source of Truth**: `docs/stacks.md` for general stack information and `docs/{pc2,pc1,idc1}-*.json` for per-stack recovery/runbook details, including ports, entrypoints, restart commands, and health checks.
*   **Local Development & Deployment**:
    *   `pc1-stack` allowed local environment overrides using `PC1_STACK_ENV_FILE` to point to a gitignored `.env.local` file.
    *   The local deploy policy on Windows mandated deploying only from `C:\chaba`, which served as the single "deploy working copy" containing complete host secret material. Development was conducted in separate worktrees (e.g., `C:\chaba_wt\...`).
*   **CI/CD Workflow**: The standard workflow involved GitHub Pull Requests targeting the `main` branch as the default integration gate. Testing and deployment were often separate, manual steps, not assumed to be part of the PR merge.
*   **Docker Management**: `mcp-docker` functioned as an HTTP wrapper around Docker MCP tools, providing an API for managing Docker containers and Compose stacks (e.g., listing containers, retrieving logs, deploying stacks). It was designed to be discoverable by `mcp0`.
*   **`dev-host` Environment**:
    *   Replaced the older `node-1` container as the canonical development target. It mirrored production nodes in terms of user accounts, SSH access, and mounted workspace, while exposing convenience routes (e.g., `/a1-idc1/*`, `/test/chat/*`) from a single container.
    *   Container structure was defined in `docker/dev-host/`, exposing ports `2223:22` (SSH) and `3100:3000` (HTTP). Volumes mounted `../:/workspace`.
    *   Secrets mirrored production environment files under `.secrets/dev-host/`, including a `publish.token` for `/api/deploy/*` endpoints. Local profiles could be overridden via `sites/dev-host/.env.dev-host`.
    *   The Express gateway (`sites/dev-host/src/server.js`) provided routing for various UI components and API proxies.
    *   API Proxies forwarded requests to backend services like Glama, Detects, Agents, MCP0, and Imagen, with configurable targets via environment variables.
    *   Health Checks: A `GET /api/health` endpoint aggregated downstream proxy checks, reporting status, HTTP status, latency, and response body.
*   **PC1 Stack Runbook**:
    *   PC1 Docker Compose stacks were reorganized into modular units: `pc1-db` (datastores), `pc1-gpu` (GPU/CUDA), `pc1-ai` (AI gateways), `pc1-devops` (DevOps automation), `pc1-web` (web UI, ingress, dev-host), `pc1-stack` (core MCP services), and `pc1-deka` (scraper).
    *   Each stack required its own `.env` file.
    *   A recommended start order was established based on service dependencies.
    *   PowerShell scripts (e.g., `scripts/pc1-*.ps1`, `scripts/pc1-start-all-stacks.ps1`) were the preferred interface for stack lifecycle management.
*   **PC1 & PC2 Reorganization Patterns**:
    *   PC1 served as the primary development and production host, featuring authentication (Authentik), webtops, and visualization tools.
    *   PC2 was a Windows worker host for specialized services like Thai language processing, meeting transcription, and AI4Thai integration.
    *   PC1's modular structure included `pc1-stack` (core MCP services), `pc1-auth` (Authentik), `pc1-web` (webtops), and `pc1-devops` (development tools).
*   **Operational Scripts**: A collection of PowerShell (`.ps1`) and Bash (`.sh`) scripts facilitated various operational tasks, including:
    *   Deploying UI components (`build-ui.sh`).
    *   Deploying sites to remote hosts (`deploy-a1-idc1.sh`, `deploy-dev-host-mirror.sh`, `deploy-node-1.sh`).
    *   Managing Caddy ingress configurations (`apply-host-caddy-deka.ps1`, `pc1-caddy-*.ps1`, `idc1-caddy-*.sh`).
    *   Managing Docker Compose stacks (`scripts/stack.ps1`, `scripts/pc1-*.ps1`, `scripts/idc1-stack.ps1`).
    *   Performing diagnostics and collecting logs (`diagnostics-a1-idc1.sh`, `idc1-log-bundle.sh`, `pc1-caddy-logs.ps1`).
    *   Specific IDC1 operations like Code Server management, VPN fixes, and health sweeps.
    *   `dever-deploy-git-branch.ps1` for git branch-based deployments.
*   **Survival into `chaba`/`ada-pi`**: The modular Docker Compose stack approach, the concept of a dedicated development environment (like `dev-host`), the `mcp-docker` pattern for API-driven Docker management, the use of `mcp-tester` for automated testing, the general CI/CD workflow of PRs to `main`, and the importance of aggregated health checks likely survived and evolved into the successor projects.
*   **Dropped from `chaba`/`ada-pi`**: Specific hostnames (e.g., `pc1.vpn`, `idc1.surf-thailand.com`), the `C:\chaba` Windows-specific deploy policy, and the `node-1` container (already superseded by `dev-host` in `chaba0`). The specific `pc1-db`, `pc1-gpu`, etc., stack names were likely replaced, though the underlying principle of modularization continued.

## Not preserved
*   The specific `C:\chaba` local deploy policy for Windows hosts, as successor projects likely adopted more platform-agnostic or containerized deployment strategies.
*   The `node-1` container, which was already superseded by the `dev-host` environment within `chaba0`.
*   The detailed, host-specific runbooks for `pc1` and `idc1` (e.g., `docs/pc1-runbook.md`, `docs/pc1-pc2-reorganization-patterns.md`), as the underlying infrastructure and host configurations would have evolved significantly in `chaba`/`ada-pi`. The *principles* of modularization and dependency-based startup would be preserved, but the exact commands and stack compositions would change.
*   The `TODO.md` and `docs/backlog.md` items, as these represented future work for `chaba0` and would be re-evaluated or completed in the successor projects.
*   The specific hostnames and network configurations (e.g., `pc1.vpn`, `a1.idc1.surf-thailand.com`), which are environment-specific and would be replaced by new infrastructure details.

## Source map

- `docs/runbooks, scripts/, tools/, backlog` → report sections above (bundle: file headers/READMEs/first-60-lines per file, 106 files)
