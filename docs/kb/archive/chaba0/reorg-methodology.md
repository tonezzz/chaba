---
kind: archive-report
bank: chaba-archive
source_repo: chaba0
source_commit: b5f1a6268e3e754a3281c55261a4ba7c8980bae9
topic: reorg-methodology
status: historical
period: [2025-12, 2026-01]
follows: []

covers:
  - docs/pc1-pc2-reorganization-patterns.md
  - docs/stack-reorganization-patterns.md
extracted: 2026-09-24
extracted_by: gemini-2.5-flash (benchmark)
---

# Reorg Methodology — archive of chaba0

## Summary
This topic outlines the methodology for reorganizing monolithic application stacks into modular, functionally separated components within the `chaba0` project. It established core principles like functional separation, standardized cross-stack communication, and host-specific port allocation. The methodology was initially derived from `idc1-stacks` and then specifically applied and adapted for `pc1` and `pc2` environments.

## Timeline
dates unknown — frozen 2026-03-28

## Still-true facts
*   Functional separation of services (Core, AI, DB, Web, DevOps, Line) [still-true]
*   Use of external networks with consistent naming (`{stack}-{host}-net`) for cross-stack communication [still-true]
*   Modular stack structure (`stacks/{host}-stack`, `stacks/{host}-{function}/`) [still-true]
*   Service distribution rules (e.g., Core stack for MCP aggregation, AI stack for inference) [still-true]
*   The principle of adapting reorganization patterns to host-specific characteristics [still-true]
*   Specific port ranges for `idc1`, `pc1`, `pc2` within `chaba0` [historical]
*   The specific modular structure and service assignments for `pc1` and `pc2` within `chaba0` [historical]

## Key details
The reorganization methodology focused on breaking down monolithic stacks into smaller, manageable units.

**Core Principles:**
*   **Functional Separation**: Services were grouped by their primary function into categories: `Core` (MCP aggregation), `AI` (ML/inference), `DB` (data storage), `Web` (UIs), `DevOps` (dev/testing tools), and `Line` (host-specific integrations).
*   **Cross-Stack Communication**: Standardized external networks (`{stack}-{host}-net`) were used for inter-stack communication, with a consistent `EXTERNAL_SERVICE_URL` environment variable pattern.
*   **Port Allocation Strategy**: Host-specific port ranges were maintained to avoid conflicts, e.g., `idc1` used 84xx (MCP), 11xxx (AI); `pc1` used 80xx/82xx (MCP), 30xx (Web).

**Architecture Patterns:**
*   **Modular Stack Structure**: A directory structure was defined where `stacks/{host}-stack/` contained core services, and `stacks/{host}-{function}/` housed specialized stacks (e.g., `pc1-ai/`, `pc1-web/`).
*   **Service Distribution Rules**: Specific services were assigned to particular stacks. For instance, `Core Stack` (`{host}-stack/`) included MCP aggregation (`1mcp-agent`) and essential MCP services. `AI Stack` (`{host}-ai/`) contained inference servers like `ollama`.

**Host-Specific Adaptations:**
*   **idc1**: Served as the initial learning ground for these patterns.
*   **PC1 (Production/Development Host)**: Characterized by authentication (Authentik), webtops, visualization tools, and external Redis/PostgreSQL dependencies. Its modular structure included `pc1-stack` (core MCP), `pc1-auth` (Authentik), `pc1-web` (webtops), and `pc1-devops` (dev tools).
*   **PC2 (Windows Worker Host)**: Focused on Windows-based development, Thai language processing, meeting transcription, and AI4Thai integration.

**Survival into `chaba`/`ada-pi`:**
The fundamental principles of functional separation, modular stack architecture, and standardized cross-stack communication were core architectural tenets that carried forward into successor projects like `chaba` and `ada-pi`. The methodology for adapting these principles to host-specific requirements also survived.

**Dropped from `chaba`/`ada-pi`:**
The specific, hardcoded port ranges and detailed service distributions for `idc1`, `pc1`, and `pc2` as defined in `chaba0` were not directly copied.

## Not preserved
The highly specific port ranges and the exact, detailed service distributions for `idc1`, `pc1`, and `pc2` as concrete configurations were deliberately not preserved as direct blueprints for `chaba`/`ada-pi`. This was because these configurations were tailored to the `chaba0` environment's specific host roles and infrastructure, which were expected to evolve or be re-evaluated in successor projects. While the *principles* of host-specific adaptation and structured port management were preserved, the *concrete values* and specific service assignments for these legacy hosts were considered `chaba0`-specific and subject to change.

## Source map

- `docs/*reorganization*` → report sections above (bundle: file headers/READMEs/first-60-lines per file, 2 files)
