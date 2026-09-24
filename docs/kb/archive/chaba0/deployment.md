---
kind: archive-report
bank: chaba-archive
source_repo: chaba0
source_commit: b5f1a6268e3e754a3281c55261a4ba7c8980bae9
topic: deployment
status: historical
period: [2025-12, 2026-03]
follows: []
superseded_by: deploy-ada.sh + idc01 service model
covers:
  - docs/line-webhook-deployment.md
  - docs/mcp-nodehost.md
  - installer/README.md
  - installer/configs/node-1.example.yaml
  - installer/package.json
  - installer/src/cli/index.js
  - installer/src/config/loader.js
extracted: 2026-09-24
extracted_by: gemini-2.5-flash (benchmark)
---

# Deployment — archive of chaba0

## Summary
This topic details the deployment strategies and tools used or planned within the `chaba0` project. It covers the specific manual steps for deploying the `mcp-line` webhook receiver to the `idc1` stack, including LINE console configuration and Docker Compose execution. Additionally, it outlines the planned `mcp-nodehost` service for app orchestration and introduces a generic `service-installer` CLI tool designed for distributed service deployment via SSH.

## Timeline
dates unknown — frozen 2026-03-28

## Still-true facts
*   The concept of deploying specific microservices (e.g., `mcp-line`) to distinct environments/stacks. [still-true]
*   The need for secure configuration management for external API credentials (e.g., LINE Channel Secret, Access Token). [still-true]
*   The use of Docker and Docker Compose for defining and orchestrating services in deployment environments. [still-true]
*   The `mcp-line` service was designed to integrate with the LINE Messaging API via webhooks. [still-true]
*   The `idc1` stack was a specific deployment target environment used in `chaba0`. [historical]
*   The specific LINE Channel ID, Secret, and Access Token provided in the guide were example credentials for `chaba0` and are no longer valid. [historical]
*   The `mcp-nodehost` service was a planned component for application orchestration, intended to replace `mcp-apphost`. [historical]
*   The `service-installer` CLI provided a framework for declarative, SSH-based deployment and status checks. [superseded-by more integrated CI/CD pipelines in `chaba`/`ada-pi`]

## Key details
*   **LINE Webhook Deployment (`mcp-line` on `idc1` stack):**
    *   **Purpose:** To receive webhook events from the LINE Platform and integrate them with `chaba0`.
    *   **Service:** `mcp-line`, a dedicated webhook receiver service.
    *   **Architecture:** LINE Platform → HTTPS → `line.idc1.surf-thailand.com` → Caddy (reverse proxy) → `mcp-line:8088`.
    *   **Configuration:** Required setup in the LINE Developers Console (creating a Messaging API channel, noting Channel ID, Secret, Access Token, and setting the Webhook URL to `https://line.idc1.surf-thailand.com/webhook/line`). Environment variables (`LINE_CHANNEL_SECRET`, `LINE_CHANNEL_ACCESS_TOKEN`, `MCP_LINE_PORT`) were configured in the `idc1-stack/.env` file.
    *   **Deployment Method:** Manual execution of a PowerShell script (`idc1-stack.ps1`) to bring up the Docker Compose stack.
    *   **Verification:** Health checks (`/health`) and testing the webhook endpoint (`/webhook/line`).
    *   **Survival into `chaba`/`ada-pi`:** The core concept of LINE integration and a dedicated webhook service likely survived, but the specific `idc1` stack and manual deployment steps were abstracted or automated within `chaba`/`ada-pi`'s more mature infrastructure.
*   **`mcp-nodehost` (Planned App Orchestrator):**
    *   **Purpose:** Intended as an app builder/orchestrator service, replacing `mcp-apphost`. It was designed to manage and host applications.
    *   **Status in `chaba0`:** This component was in a "planned" state at the time of the archive. Its service code (`mcp/mcp-nodehost/`) and stack configuration files (`stacks/app-demo/docker-compose.yml`, `Caddyfile`) were not yet present or fully implemented.
    *   **Intended Layout:** Service code in `mcp/mcp-nodehost/`, with Docker Compose and Caddy configurations in `stacks/app-demo/`.
    *   **Survival into `chaba`/`ada-pi`:** The *need* for an app orchestration component undoubtedly survived, but the specific `mcp-nodehost` implementation or naming might have evolved significantly or been absorbed into a broader platform management system in `chaba`/`ada-pi`.
*   **`service-installer` CLI:**
    *   **Purpose:** A generic command-line interface tool for deploying and managing services across distributed targets. It aimed to provide a standardized way to push code and execute commands remotely.
    *   **Commands:** `service-installer deploy <service>` (to deploy a specified service to configured targets, including a `dry-run` option) and `service-installer status <service>` (to check the deployment status of a service on all targets).
    *   **Configuration:** Utilized YAML configuration files (e.g., `configs/targets.example.yaml`, `node-1.example.yaml`) to define:
        *   `targets`: Remote hosts, including connection details (host, port, username, authentication method), environment variables, and optional `preCommands`/`postCommands`.
        *   `services`: Service definitions, specifying artifact sources (e.g., Git repository and branch), and lifecycle commands (`setup`, `start`, `status`, `health`) to be executed on the targets.
    *   **Technology:** Implemented in Node.js, leveraging `node-ssh` for secure remote command execution.
    *   **Survival into `chaba`/`ada-pi`:** The *concept* of a declarative, configuration-driven deployment tool for distributed services strongly influenced `chaba`/`ada-pi`. While the specific `service-installer` CLI might not have been carried forward as a standalone tool, its principles of defining targets and service lifecycle commands were likely integrated into a more comprehensive CI/CD or platform management system.

## Not preserved
*   The specific `idc1` stack deployment script and its manual execution steps were not preserved as a primary deployment method in `chaba`/`ada-pi`. This was superseded by more automated and generic CI/CD pipelines to improve efficiency and reliability.
*   The explicit `mcp-nodehost` renaming and its incomplete implementation state were not directly carried forward. The functionality it aimed to provide was likely integrated into a different, more mature orchestration layer within `chaba`/`ada-pi`.
*   The `service-installer` CLI, while a functional proof-of-concept, was likely not preserved as a standalone tool in `chaba`/`ada-pi`. Its core logic and configuration patterns were absorbed into a more robust, centralized deployment system or platform, making the standalone CLI redundant for the successor projects.
*   The specific LINE Channel ID, Secret, and Access Token provided in the `docs/line-webhook-deployment.md` were not preserved due to security reasons and their ephemeral nature as test or development credentials.

## Source map

- `installer/, docs/line-webhook-deployment.md, docs/mcp-nodehost.md` → report sections above (bundle: file headers/READMEs/first-60-lines per file, 7 files)
